"""Fine-tune an event/profile cross-encoder and measure extraction error propagation."""

import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import torch
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.modeling.data import Document, span_key
from smartnotice.modeling.experiment import (
    Settings,
    checkpoint_weights,
    configure_encoder,
    make_optimizer,
    optimizer_step,
    restore_weights,
    write_summary,
)
from smartnotice.modeling.metrics import classification, event_keys, prf_counts
from smartnotice.schemas import Annotation, Event, Notice, Profile
from torch.nn import functional as F
from transformers import AutoModelForSequenceClassification, get_linear_schedule_with_warmup

LABELS = ("APPLIES", "NOT_APPLIES", "UNCLEAR")
FIELDS = {
    "cohort": "Khóa tuyển sinh",
    "degree_level": "Bậc học",
    "major": "Ngành",
    "program": "Chương trình",
    "status": "Trạng thái",
}


def event_context(notice: Notice, annotation: Annotation, event: Event) -> str:
    """Serialize source phrases and evidence for a specific action."""
    spans = {s.span_id: s for s in annotation.spans}
    sentences = {s.sentence_id: s for s in notice.sentences}
    source = [sentences[sid] for sid in event.evidence_sentence_ids]
    action = spans[event.action_span_id]
    arguments = [spans[a.span_id] for a in event.arguments]
    audience = [s.text for s in arguments if s.label == "AUDIENCE"]
    conditions = [s.text for s in arguments if s.label == "CONDITION"]
    return "\n".join(
        [
            f"Công việc: {action.text}",
            *(f"Đối tượng: {text}" for text in audience),
            *(f"Điều kiện: {text}" for text in conditions),
            *(s.text for s in sorted(source, key=lambda s: s.start)),
        ]
    )


def profile_text(profile: dict) -> str:
    """Render only profile fields available at inference, including missing values."""
    return " | ".join(
        f"{label}: {profile[field] if profile[field] is not None else 'chưa cung cấp'}"
        for field, label in FIELDS.items()
    )


def build_examples(
    docs: list[Document],
    profiles: list[Profile],
    rng: random.Random,
    cap: int | None = None,
) -> list[dict]:
    """Use existing silver rules and optionally subsample each training event/class."""
    rows = []
    for doc in docs:
        contexts = {
            event.event_id: event_context(doc.notice, doc.annotation, event)
            for event in doc.annotation.events
        }
        pairs = build_pairs([doc.notice], [doc.annotation], profiles)
        if cap is not None:
            groups = defaultdict(list)
            for row in pairs:
                groups[row["event_id"], row["label"]].append(row)
            pairs = [
                row
                for selected in groups.values()
                for row in rng.sample(selected, min(cap, len(selected)))
            ]
        rows.extend(
            {
                "doc_id": row["doc_id"],
                "event_id": row["event_id"],
                "profile_id": row["profile_id"],
                "context": contexts[row["event_id"]],
                "profile": profile_text(row["profile"]),
                "label": row["label"],
                "reason": row["rule_reason"],
            }
            for row in pairs
        )
    return rows


def batch_encoding(rows: list[dict], tokenizer, length: int, device) -> dict:
    """Tokenize event/profile pairs and preserve the profile when trimming context."""
    return tokenizer(
        [row["context"] for row in rows],
        [row["profile"] for row in rows],
        max_length=length,
        truncation="only_first",
        padding=True,
        return_tensors="pt",
    ).to(device)


@torch.no_grad()
def predict_logits(model, tokenizer, rows: list[dict], length: int, device) -> torch.Tensor:
    """Score event/profile rows in batches with stable ordering."""
    model.eval()
    batches = []
    for first in range(0, len(rows), 16):
        with torch.autocast(device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            result = model(**batch_encoding(rows[first : first + 16], tokenizer, length, device))
        batches.append(result.logits.float().cpu())
    return torch.cat(batches) if batches else torch.empty((0, len(LABELS)))


def calibration(logits: torch.Tensor, expected: list[str]) -> dict:
    """Fit validation temperature and choose a high-confidence operating point."""
    targets = torch.tensor([LABELS.index(v) for v in expected])
    log_t = torch.zeros((), requires_grad=True)
    optimizer = torch.optim.LBFGS([log_t], max_iter=25, line_search_fn="strong_wolfe")

    def closure():
        optimizer.zero_grad()
        loss = F.cross_entropy(logits / log_t.clamp(-3, 3).exp(), targets)
        loss.backward()
        return loss

    optimizer.step(closure)
    temperature = float(log_t.detach().clamp(-3, 3).exp())
    scores, predictions = (logits / temperature).softmax(dim=1).max(dim=1)
    correct = predictions == targets
    grid = []
    for threshold in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9):
        accepted = scores >= threshold
        count = int(accepted.sum())
        grid.append(
            {
                "threshold": threshold,
                "accepted": count,
                "coverage": count / len(targets),
                "accepted_accuracy": float(correct[accepted].float().mean()) if count else None,
            }
        )
    chosen = next((row for row in grid if (row["accepted_accuracy"] or 0) >= 0.8), None)
    return {
        "temperature": temperature,
        "validation_nll_before": float(F.cross_entropy(logits, targets)),
        "validation_nll_after": float(F.cross_entropy(logits / temperature, targets)),
        "chosen": chosen,
        "validation_operating_points": grid,
    }


def propagated_scores(
    model,
    tokenizer,
    validation,
    rows,
    predictions,
    profiles,
    settings,
    device,
) -> dict:
    """Score matched-event applicability and full joint event/profile exactness."""
    gold_rows = {(r["doc_id"], r["event_id"], r["profile_id"]): r["label"] for r in rows}
    by_key, predicted_rows, gold_joint, matches = {}, [], set(), set()
    spurious_pairs = 0
    for doc in validation:
        doc_id = doc.notice.doc_id
        predicted = predictions[doc_id]
        gold = doc.annotation
        gold_spans = {s.span_id: span_key(s) for s in gold.spans}
        pred_spans = {s.span_id: span_key(s) for s in predicted.spans}
        gold_events = {gold_spans[e.action_span_id]: e for e in gold.events}
        gold_event_keys = event_keys(gold)
        pred_event_keys = event_keys(predicted)
        for action, event in gold_events.items():
            for profile in profiles:
                key = doc_id, event.event_id, profile.profile_id
                gold_joint.add(
                    (doc_id, action, gold_event_keys[action], profile.profile_id, gold_rows[key])
                )
                by_key[doc_id, action, profile.profile_id] = gold_rows[key]
        for event in predicted.events:
            action = pred_spans[event.action_span_id]
            if action not in gold_events:
                spurious_pairs += len(profiles)
                continue
            matches.add((doc_id, action))
            context = event_context(doc.notice, predicted, event)
            for profile in profiles:
                predicted_rows.append(
                    {
                        "context": context,
                        "profile": profile_text(profile.model_dump()),
                        "identity": (doc_id, action, profile.profile_id),
                        "args": pred_event_keys[action],
                    }
                )
    logits = predict_logits(model, tokenizer, predicted_rows, settings.length, device)
    predictions = [LABELS[i] for i in logits.argmax(dim=1).tolist()]
    expected_when_matched, predicted_when_matched, joint = [], [], set()
    for row, label in zip(predicted_rows, predictions, strict=True):
        key = row["identity"]
        if key in by_key:
            expected_when_matched.append(by_key[key])
            predicted_when_matched.append(label)
        doc_id, action, profile_id = key
        joint.add((doc_id, action, row["args"], profile_id, label))
    return {
        "matched_action_events": len(matches),
        "expected_events": sum(len(doc.annotation.events) for doc in validation),
        "matched_action_applicability": classification(
            expected_when_matched, predicted_when_matched, LABELS
        ),
        "joint_exact_event_profile": prf_counts(
            len(gold_joint & joint), len(joint) + spurious_pairs, len(gold_joint)
        ),
    }


def train_applicability(
    train: list[Document],
    validation: list[Document],
    predictions: dict,
    checkpoint: str,
    tokenizer,
    settings: Settings,
    output: Path,
    device,
) -> dict:
    """Fine-tune pretrained weights and score annotated and predicted event context."""
    rng = random.Random(settings.seed)
    torch.manual_seed(settings.seed)
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    profiles = generate_profiles(
        [c for doc in train for c in doc.annotation.audience_constraints], settings.seed
    )
    panel = rng.sample(profiles, min(settings.app_eval_profiles, len(profiles)))
    fitting = build_examples(train, profiles, rng, settings.app_training_pairs_per_class)
    valid = build_examples(validation, panel, rng)
    targets = [row["label"] for row in valid]
    if not fitting or not valid:
        raise ValueError("Applicability training needs supervised event/profile examples")
    model = AutoModelForSequenceClassification.from_pretrained(
        checkpoint,
        num_labels=len(LABELS),
        label2id={c: i for i, c in enumerate(LABELS)},
        id2label=dict(enumerate(LABELS)),
    ).to(device)
    configure_encoder(model.base_model, settings)
    optimizer = make_optimizer(model.base_model, model.classifier.parameters(), settings)
    batches = (len(fitting) + settings.app_batch_size - 1) // settings.app_batch_size
    accumulate = 2
    steps = settings.app_epochs * ((batches + accumulate - 1) // accumulate)
    scheduler = get_linear_schedule_with_warmup(optimizer, max(1, steps // 10), steps)
    scaler = torch.amp.GradScaler(device.type, enabled=device.type == "cuda")
    best = -1.0
    history = []
    started = time.perf_counter()
    checkpoint_file = output / "applicability.pt"
    for epoch in range(settings.app_epochs):
        model.train()
        rng.shuffle(fitting)
        losses = []
        for number, first in enumerate(range(0, len(fitting), settings.app_batch_size), 1):
            rows = fitting[first : first + settings.app_batch_size]
            labels = torch.tensor([LABELS.index(row["label"]) for row in rows], device=device)
            with torch.autocast(device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                loss = model(
                    **batch_encoding(rows, tokenizer, settings.length, device), labels=labels
                ).loss
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite applicability loss")
            scale = 1 if number == batches and batches % accumulate else accumulate
            scaler.scale(loss / scale).backward()
            losses.append(loss.item())
            if number % accumulate == 0 or number == batches:
                optimizer_step(model, optimizer, scheduler, scaler)
            if number % 50 == 0:
                write_summary(
                    output / "progress.json",
                    {
                        "stage": "applicability",
                        "epoch": epoch + 1,
                        "batches_completed": number,
                        "batches_total": batches,
                        "average_loss": sum(losses) / len(losses),
                    },
                )
        logits = predict_logits(model, tokenizer, valid, settings.length, device)
        labels = [LABELS[i] for i in logits.argmax(dim=1).tolist()]
        result = classification(targets, labels, LABELS)
        row = {
            "epoch": epoch + 1,
            "loss": sum(losses) / len(losses),
            "validation_macro_f1": result["macro_f1"],
        }
        history.append(row)
        print(row, flush=True)
        if result["macro_f1"] > best:
            best = result["macro_f1"]
            torch.save(checkpoint_weights(model, settings), checkpoint_file)
            write_summary(output / "applicability_annotated_metrics.json", result)
    del optimizer, scheduler
    restore_weights(model, torch.load(checkpoint_file, map_location="cpu"), settings)
    logits = predict_logits(model, tokenizer, valid, settings.length, device)
    labels = [LABELS[i] for i in logits.argmax(dim=1).tolist()]
    subsets = {}
    for reason in (
        "excluded_status",
        "implicit_audience",
        "missing_profile_attribute",
        "unmodeled_condition",
        "unrepresented_requirement",
    ):
        subset = [i for i, row in enumerate(valid) if row["reason"] == reason]
        subsets[reason] = classification(
            [targets[i] for i in subset], [labels[i] for i in subset], LABELS
        )
    result = {
        "label_origin": "constraint_rule",
        "training_pairs_by_class": dict(Counter(row["label"] for row in fitting)),
        "profile_bank_size": len(profiles),
        "validation_profile_panel_size": len(panel),
        "validation_profile_ids": [p.profile_id for p in panel],
        "annotated_events": classification(targets, labels, LABELS),
        "annotated_event_subsets": subsets,
        "predicted_events": propagated_scores(
            model, tokenizer, validation, valid, predictions, panel, settings, device
        ),
        "calibration": calibration(logits, targets),
        "history": history,
        "training_seconds_including_validation": time.perf_counter() - started,
        "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
        "peak_cuda_bytes": torch.cuda.max_memory_allocated(device)
        if device.type == "cuda"
        else None,
    }
    write_summary(output / "applicability_metrics.json", result)
    return result
