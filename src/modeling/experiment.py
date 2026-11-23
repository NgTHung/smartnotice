"""Run the shared extraction model on the frozen development split."""

import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from smartnotice.modeling.data import (
    TokenDocument,
    labeled_links,
    span_key,
)
from smartnotice.modeling.extraction import Extractor, decode
from smartnotice.modeling.metrics import (
    date_map,
    date_scores,
    event_keys,
    link_scores,
    prf,
    relation_confusion,
    span_scores,
)
from smartnotice.preprocessing.split import DEFAULT_SEED
from transformers import AutoModel, get_linear_schedule_with_warmup

SPAN_THRESHOLDS = (0.10, 0.15, 0.20, 0.25, 0.35, 0.50, 0.65, 0.80, 0.90)
LINK_THRESHOLDS = (0.50, 0.65, 0.80)


@dataclass(frozen=True)
class Settings:
    """Record pilot training settings, including token budgets and the random seed."""

    seed: int = DEFAULT_SEED
    tuning: str = "full"
    lora_rank: int = 8
    lora_alpha: int = 16
    lora_lr: float = 1e-4
    length: int = 256
    overlap: int = 96
    warm_epochs: int = 1
    joint_epochs: int = 3
    app_epochs: int = 2
    accumulation: int = 8
    app_batch_size: int = 6
    app_training_pairs_per_class: int = 2
    app_eval_profiles: int = 24
    span_limit: int = 160
    span_positive_weight: float = 8.0
    suppress_same_type_overlap: bool = False
    encoder_lr: float = 2e-5
    head_lr: float = 3e-4


def write_summary(path: Path, summary: dict) -> None:
    """Persist aggregate experiment or stage metadata as UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_optimizer(encoder, heads, settings: Settings) -> torch.optim.AdamW:
    """Optimize the trainable encoder parameters and task heads."""
    encoder_lr = settings.lora_lr if settings.tuning == "lora" else settings.encoder_lr
    return torch.optim.AdamW(
        [
            {"params": [p for p in encoder.parameters() if p.requires_grad], "lr": encoder_lr},
            {"params": [p for p in heads if p.requires_grad], "lr": settings.head_lr},
        ],
        weight_decay=0.01,
        foreach=False,
    )


def configure_encoder(encoder, settings: Settings) -> None:
    """Enable activation checkpointing and optionally inject trainable LoRA adapters."""
    if settings.tuning == "lora":
        from peft import LoraConfig, inject_adapter_in_model

        config = LoraConfig(
            r=settings.lora_rank,
            lora_alpha=settings.lora_alpha,
            lora_dropout=0.05,
            target_modules=["query", "value"],
            bias="none",
        )
        inject_adapter_in_model(config, encoder)
    elif settings.tuning != "full":
        raise ValueError("Tuning mode must be full or lora")
    encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})


def checkpoint_weights(model, settings: Settings) -> dict:
    """Save full weights or the trainable adapter and task-head tensors."""
    state = model.state_dict()
    if settings.tuning == "lora":
        trainable = {key for key, param in model.named_parameters() if param.requires_grad}
        state = {key: value for key, value in state.items() if key in trainable}
    return state


def restore_weights(model, state: dict, settings: Settings) -> None:
    """Reload a saved checkpoint into the same pretrained architecture."""
    if settings.tuning == "lora" and state.keys() != checkpoint_weights(model, settings).keys():
        raise ValueError("Adapter checkpoint does not match the configured trainable parameters")
    model.load_state_dict(state, strict=settings.tuning == "full")


def load_extractor(
    base: str | Path, checkpoint: dict, pad_id: int, settings: Settings, device: torch.device
) -> Extractor:
    """Reconstruct the trained span and relation heads from verified base weights."""
    encoder = AutoModel.from_pretrained(base, add_pooling_layer=False)
    configure_encoder(encoder, settings)
    model = Extractor(encoder, checkpoint["width"], pad_id)
    restore_weights(model, checkpoint["state_dict"], settings)
    return model.to(device)


def optimizer_step(model, optimizer, scheduler, scaler) -> None:
    """Clip unscaled gradients, then advance the optimizer and scheduler."""
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    previous_scale = scaler.get_scale()
    scaler.step(optimizer)
    scaler.update()
    if scaler.get_scale() >= previous_scale:
        scheduler.step()
    optimizer.zero_grad(set_to_none=True)


def evaluate_extraction(model, validation: list[TokenDocument], settings: Settings) -> tuple:
    """Select validation thresholds and return scores, evidence predictions, and thresholds."""
    model.eval()
    gold_spans, gold_links, candidate_spans, available_links = set(), set(), set(), set()
    cache = []
    for doc in validation:
        annotation = doc.document.annotation
        ident = annotation.doc_id
        expected = {span_key(s) for s in annotation.spans}
        expected_links = labeled_links(annotation)
        representable = {s for s in expected if s[:2] in doc.candidates}
        gold_spans.update((ident, *s) for s in expected)
        candidate_spans.update((ident, *s) for s in representable)
        gold_links.update((ident, *link) for link in expected_links)
        available_links.update(
            (ident, a, b, role)
            for a, b, role in expected_links
            if a in representable and b in representable
        )
        pred_spans, scores = model.predict(
            doc,
            SPAN_THRESHOLDS,
            settings.span_limit,
            suppress_same_type_overlap=settings.suppress_same_type_overlap,
        )
        cache.append((doc, ident, representable, pred_spans, scores))

    span_grid = {}
    pair_grid = {}
    span_sets = {}
    for span_threshold in SPAN_THRESHOLDS:
        spans = {
            (ident, *span) for _, ident, _, traces, _ in cache for span in traces[span_threshold]
        }
        span_sets[span_threshold] = spans
        span_grid[span_threshold] = prf(gold_spans, spans)
        for link_threshold in LINK_THRESHOLDS:
            selected = {
                (ident, a, b, role)
                for _, ident, _, traces, scores in cache
                for (a, b, role), score in scores.items()
                if score >= link_threshold
                and a in traces[span_threshold]
                and b in traces[span_threshold]
            }
            pair_grid[span_threshold, link_threshold] = prf(gold_links, selected)

    best = max(
        pair_grid,
        key=lambda pair: (
            pair_grid[pair]["f1"],
            span_grid[pair[0]]["f1"],
            pair[1],
            pair[0],
        ),
    )
    span_cut, link_cut = best
    oracle_cut = max(
        LINK_THRESHOLDS,
        key=lambda threshold: prf(
            gold_links,
            {
                (ident, a, b, role)
                for _, ident, expected, _, scores in cache
                for (a, b, role), score in scores.items()
                if score >= threshold and a in expected and b in expected
            },
        )["f1"],
    )
    predictions = {}
    predicted_links, oracle_links, end_to_end_candidates = set(), set(), set()
    events, gold_events = set(), set()
    dates, gold_dates = {}, {}
    for doc, ident, expected, traces, scores in cache:
        spans = traces[span_cut]
        links = {
            (a, b, role)
            for (a, b, role), score in scores.items()
            if score >= link_cut and a in spans and b in spans
        }
        predicted_links.update((ident, *link) for link in links)
        oracle_links.update(
            (ident, a, b, role)
            for (a, b, role), score in scores.items()
            if score >= oracle_cut and a in expected and b in expected
        )
        end_to_end_candidates.update(
            (ident, a, b, role)
            for a, b, role in labeled_links(doc.document.annotation)
            if a in spans and b in spans
        )
        prediction = decode(doc, spans, links)
        predictions[ident] = prediction
        events.update((ident, action, args) for action, args in event_keys(prediction).items())
        gold_events.update(
            (ident, action, args) for action, args in event_keys(doc.document.annotation).items()
        )
        dates.update(date_map(prediction))
        gold_dates.update(date_map(doc.document.annotation))

    thresholds = {"span": span_cut, "link": link_cut, "oracle_link": oracle_cut}
    summary = {
        "thresholds": thresholds,
        "candidate_spans": sum(len(doc.candidates) for doc in validation),
        "span_candidate_recall": prf(gold_spans, candidate_spans)["recall"],
        "oracle_link_candidate_recall": prf(gold_links, available_links)["recall"],
        "predicted_link_candidate_recall": prf(gold_links, end_to_end_candidates)["recall"],
        "span": span_scores(gold_spans, span_sets[span_cut]),
        "link_annotated_endpoints": link_scores(gold_links, oracle_links),
        "link_annotated_confusion": relation_confusion(
            {ident: expected for _, ident, expected, _, _ in cache},
            gold_links,
            oracle_links,
        ),
        "link_predicted_endpoints": link_scores(gold_links, predicted_links),
        "exact_event": prf(gold_events, events),
        "normalized_dates": date_scores(gold_dates, dates),
        "span_threshold_grid": span_grid,
        "joint_threshold_grid": {f"{a}/{b}": result for (a, b), result in pair_grid.items()},
    }
    return summary, predictions


def train_extraction(
    train: list[TokenDocument],
    validation: list[TokenDocument],
    checkpoint: str,
    pad_id: int,
    width: int,
    settings: Settings,
    output: Path,
    device: torch.device,
) -> tuple:
    """Warm start the span head, then select a joint checkpoint by validation link F1."""
    torch.manual_seed(settings.seed)
    rng = random.Random(settings.seed)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    encoder = AutoModel.from_pretrained(checkpoint, add_pooling_layer=False)
    configure_encoder(encoder, settings)
    model = Extractor(encoder, width, pad_id).to(device)
    heads = [p for name, p in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = make_optimizer(encoder, heads, settings)
    epochs = settings.warm_epochs + settings.joint_epochs
    steps = epochs * ((len(train) + settings.accumulation - 1) // settings.accumulation)
    scheduler = get_linear_schedule_with_warmup(optimizer, max(1, steps // 10), steps)
    scaler = torch.amp.GradScaler(device.type, enabled=device.type == "cuda")
    history = []
    best = None
    best_result = None
    checkpoint_file = output / "extraction.pt"
    started = time.perf_counter()

    for epoch in range(epochs):
        model.train()
        order = rng.sample(range(len(train)), len(train))
        joint = epoch >= settings.warm_epochs
        losses = []
        for step, index in enumerate(order, 1):
            division = min(
                settings.accumulation,
                len(train) - ((step - 1) // settings.accumulation) * settings.accumulation,
            )
            with torch.autocast(device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                loss = model.loss(train[index], rng, joint, settings.span_positive_weight)
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite extraction loss")
            scaler.scale(loss / division).backward()
            losses.append(loss.detach().item())
            if step % settings.accumulation == 0 or step == len(order):
                optimizer_step(model, optimizer, scheduler, scaler)
            if step % 50 == 0:
                write_summary(
                    output / "progress.json",
                    {
                        "stage": "joint" if joint else "span",
                        "epoch": epoch + 1,
                        "docs_completed": step,
                        "docs_total": len(order),
                        "average_loss": sum(losses) / len(losses),
                    },
                )
        row = {"epoch": epoch + 1, "joint": joint, "loss": sum(losses) / len(losses)}
        if joint:
            result, predictions = evaluate_extraction(model, validation, settings)
            score = (result["link_predicted_endpoints"]["micro"]["f1"], result["exact_event"]["f1"])
            row["validation_link_f1"] = score[0]
            if best is None or score > best:
                best = score
                best_result = result, predictions
                torch.save(
                    {
                        "state_dict": checkpoint_weights(model, settings),
                        "width": width,
                        "thresholds": result["thresholds"],
                        "epoch": epoch + 1,
                        "settings": asdict(settings),
                    },
                    checkpoint_file,
                )
                write_summary(output / "extraction_metrics.json", result)
        history.append(row)
        write_summary(output / "extraction_history.json", {"epochs": history})
        print(row, flush=True)
    if best_result is None:
        raise ValueError("Enable at least one joint epoch")
    result, predictions = best_result
    result.update(
        {
            "training_seconds_including_validation": time.perf_counter() - started,
            "history": history,
            "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "peak_cuda_bytes": torch.cuda.max_memory_allocated(device)
            if device.type == "cuda"
            else None,
        }
    )
    write_summary(output / "extraction_metrics.json", result)
    return result, predictions
