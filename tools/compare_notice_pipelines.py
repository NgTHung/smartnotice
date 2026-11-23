"""Fit and select on development data, then score frozen pipelines on held-out references."""

import argparse
import hashlib
import json
import platform
import random
import time
from importlib.metadata import version
from pathlib import Path

import joblib
import torch
from smartnotice.io import read_jsonl
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.labeling.validation import validate_annotation
from smartnotice.modeling.applicability import LABELS, build_examples, propagated_scores
from smartnotice.modeling.contextual import (
    ContextExtractor,
    DocumentTemplateExtractor,
    TemplateExtractor,
)
from smartnotice.modeling.data import (
    Document,
    labeled_links,
    load_development,
    sha256,
    span_key,
    tokenize,
)
from smartnotice.modeling.experiment import (
    Settings,
    configure_encoder,
    load_extractor,
    restore_weights,
    write_summary,
)
from smartnotice.modeling.extraction import decode_notice
from smartnotice.modeling.metrics import (
    date_map,
    date_scores,
    event_keys,
    link_scores,
    prf,
    span_scores,
)
from smartnotice.schemas import Annotation, Notice
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _metrics(docs, outputs):
    gold_spans, spans, gold_links, links = set(), set(), set(), set()
    gold_events, events, gold_dates, dates = set(), set(), {}, {}
    for doc in docs:
        ident = doc.notice.doc_id
        predicted_spans, pred = outputs[ident]
        spans.update((ident, *s) for s in predicted_spans)
        gold_spans.update((ident, *span_key(s)) for s in doc.annotation.spans)
        for ann, ls, es, ds in (
            (doc.annotation, gold_links, gold_events, gold_dates),
            (pred, links, events, dates),
        ):
            ls.update((ident, *link) for link in labeled_links(ann))
            es.update((ident, action, args) for action, args in event_keys(ann).items())
            ds.update(date_map(ann))
    return {
        "span": span_scores(gold_spans, spans),
        "link": link_scores(gold_links, links),
        "event": prf(gold_events, events),
        "dates": date_scores(gold_dates, dates),
    }


def _context_predictions(model, docs, cutoffs):
    outputs = {cut: {} for cut in cutoffs}
    for doc in docs:
        notice = doc.notice
        if isinstance(model, DocumentTemplateExtractor):
            spans, scores = model.candidates(notice)
        else:
            spans = model.spans(notice)
            scores = list(model.links(notice, spans))
        for cut in cutoffs:
            links = {link for link, score in scores if score >= cut}
            outputs[cut][notice.doc_id] = (
                spans,
                decode_notice(notice, spans, links, "context-prediction"),
            )
    return outputs


def _bert_predictions(path, docs, base, tokenizer, device):
    saved = torch.load(path, map_location="cpu")
    settings = Settings(**saved["settings"])
    model = load_extractor(base, saved, tokenizer.pad_token_id, settings, device)
    model.eval()
    cut, link_cut = (saved["thresholds"][k] for k in ("span", "link"))
    outputs = {}
    for doc in docs:
        notice = doc.notice
        blank = Annotation(doc_id=notice.doc_id, annotator_id="inference", spans=[], events=[])
        token_doc = tokenize(
            Document(notice, blank, doc.group_id),
            tokenizer,
            settings.length,
            settings.overlap,
            saved["width"],
        )
        span_map, links = model.predict(
            token_doc,
            (cut,),
            settings.span_limit,
            suppress_same_type_overlap=settings.suppress_same_type_overlap,
        )
        spans = span_map[cut]
        chosen = {link for link, score in links.items() if score >= link_cut}
        outputs[notice.doc_id] = spans, decode_notice(notice, spans, chosen, "bamibert-prediction")
    return outputs


def _app(args, train, docs, predictions, device, tokenizer):
    settings = Settings(**_read(args.baseline / "run.json")["settings"])
    rng = random.Random(settings.seed)
    profiles = generate_profiles(
        [c for d in train for c in d.annotation.audience_constraints], settings.seed
    )
    panel = rng.sample(profiles, settings.app_eval_profiles)
    if [p.profile_id for p in panel] != _read(args.baseline / "applicability_metrics.json")[
        "validation_profile_ids"
    ]:
        raise ValueError("Applicability panel differs from the baseline")
    rows = build_examples(docs, panel, rng)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base,
        num_labels=len(LABELS),
        label2id={label: i for i, label in enumerate(LABELS)},
        id2label=dict(enumerate(LABELS)),
    )
    configure_encoder(model.base_model, settings)
    restore_weights(
        model, torch.load(args.baseline / "applicability.pt", map_location="cpu"), settings
    )
    return {
        name: propagated_scores(
            model.to(device),
            tokenizer,
            docs,
            rows,
            {k: v[1] for k, v in pred.items()},
            panel,
            settings,
            device,
        )
        for name, pred in predictions.items()
    }


def _test_docs(root):
    # Reference annotations are used for scoring only. Inference receives blank annotations.
    manifest = _read(root / "checksums.json")
    names = ["test/notices.jsonl", "reference_only_do_not_train_on_test/annotations.jsonl"]
    for name in names:
        if sha256(root / name) != manifest[name]:
            raise ValueError(f"Checksum mismatch for {name}")
    assignments = {
        r["doc_id"]: r for r in read_jsonl(root / "assignments.jsonl") if r["split"] == "test"
    }
    labels = {}
    for row in read_jsonl(root / names[1]):
        ident = row["doc_id"]
        if ident in assignments:
            if ident in labels:
                raise ValueError("Duplicate test annotation")
            labels[ident] = Annotation.model_validate(row)
    docs = []
    for row in read_jsonl(root / names[0]):
        notice = Notice.model_validate(row)
        key = notice.doc_id
        if (
            notice.synthetic
            or hashlib.sha256(notice.text.encode()).hexdigest() != assignments[key]["text_sha256"]
        ):
            raise ValueError("Test notice integrity failure")
        validate_annotation(labels[key], notice)
        docs.append(Document(notice, labels[key], assignments[key]["group_id"]))
    if len(docs) != len(assignments) or {d.notice.doc_id for d in docs} != assignments.keys():
        raise ValueError("Test notices do not match frozen assignments")
    return docs


def main() -> None:
    """Fit the contextual model, compare validation pipelines, or score the locked selection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "templates", "documents", "select", "test"))
    for name in ("split", "base", "baseline", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    docs, provenance = load_development(args.split)
    baseline = _read(args.baseline / "run.json")
    if baseline["data"]["hashes"] != provenance["hashes"]:
        raise ValueError("Baseline and Drive release differ")
    context = args.output / "context.joblib"
    locked = args.output / "selected.json"
    if args.stage != "test" and locked.exists():
        raise ValueError("Use a fresh directory for another selection")
    if args.stage in {"fit", "templates", "documents"}:
        started = time.perf_counter()
        if args.stage == "fit":
            model = ContextExtractor(baseline["settings"]["seed"])
            name = "context"
        elif args.stage == "templates":
            model = TemplateExtractor(joblib.load(context), similarity=0.65)
            name = "templates"
        else:
            model = DocumentTemplateExtractor(
                joblib.load(args.output / "templates.joblib"), similarity=0.60
            )
            name = "documents"
        model.fit(docs["train"])
        joblib.dump(model, args.output / f"{name}.joblib", compress=3)
        scores = {
            cut: _metrics(docs["validation"], pred)
            for cut, pred in _context_predictions(
                model, docs["validation"], (0.35, 0.50, 0.65)
            ).items()
        }
        write_summary(
            args.output / f"{name}_validation.json",
            {"seconds": time.perf_counter() - started, "scores": scores},
        )
        print({k: v["event"]["f1"] for k, v in scores.items()})
        return
    paths = {
        "context": context,
        "templates": args.output / "templates.joblib",
        "documents": args.output / "documents.joblib",
        "weight8": args.baseline / "extraction.pt",
        "weight2": args.output / "weight2/extraction.pt",
        "app": args.baseline / "applicability.pt",
        "base": args.base / "model.safetensors",
        "tokenizer": args.base / "tokenizer.json",
    }
    hashes = {k: sha256(v) for k, v in paths.items()}
    hashes.update(
        {
            path.name: sha256(path)
            for path in [Path(__file__), *sorted(Path("src/modeling").glob("*.py"))]
        }
    )
    if (
        hashes["base"] != baseline["model_weights_sha256"]
        or hashes["tokenizer"] != baseline["tokenizer_sha256"]
    ):
        raise ValueError("Base checkpoint or tokenizer differs from the training run")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.base, use_fast=True)
    if args.stage == "select":
        cutoffs = {}
        for name in ("context", "templates", "documents"):
            scores = _read(args.output / f"{name}_validation.json")["scores"]
            cutoffs[name] = float(
                max(
                    scores,
                    key=lambda k: (scores[k]["event"]["f1"], scores[k]["link"]["micro"]["f1"]),
                )
            )
        names = ["weight8", "weight2", "context", "templates", "documents"]
        evaluation = docs["validation"]
    else:
        freeze = _read(locked)
        if freeze["hashes"] != hashes or freeze["development_hashes"] != provenance["hashes"]:
            raise ValueError("Frozen pipeline or data changed")
        cutoffs = freeze["link_cutoffs"]
        names = list(dict.fromkeys(["weight8", freeze["winner"]]))
        evaluation = _test_docs(args.split)
    predictions = {}
    for name in names:
        if name in cutoffs:
            cut = cutoffs[name]
            predictions[name] = _context_predictions(joblib.load(paths[name]), evaluation, (cut,))[
                cut
            ]
        else:
            predictions[name] = _bert_predictions(
                paths[name], evaluation, args.base, tokenizer, device
            )
    scores = {name: _metrics(evaluation, pred) for name, pred in predictions.items()}
    for name, outputs in predictions.items():
        with (args.output / f"{args.stage}-{name}-predictions.jsonl").open(
            "w", encoding="utf-8"
        ) as stream:
            for ident, (spans, ann) in outputs.items():
                record = {
                    "doc_id": ident,
                    "typed_spans": sorted(spans),
                    "events": [
                        {"action": action, "arguments": sorted(arguments, key=repr)}
                        for action, arguments in sorted(event_keys(ann).items())
                    ],
                }
                stream.write(json.dumps(record, default=str) + "\n")
    applicability = _app(args, docs["train"], evaluation, predictions, device, tokenizer)
    metadata = {
        "documents": len(evaluation),
        "groups": len({d.group_id for d in evaluation}),
        "scores": scores,
        "applicability": applicability,
    }
    if args.stage == "select":
        winner = max(
            names, key=lambda n: (scores[n]["event"]["f1"], scores[n]["link"]["micro"]["f1"])
        )
        write_summary(args.output / "validation.json", metadata)
        write_summary(
            locked,
            {
                "winner": winner,
                "criterion": "exact event F1, then exact link micro-F1",
                "link_cutoffs": cutoffs,
                "hashes": hashes,
                "development_hashes": provenance["hashes"],
                "seed": baseline["settings"]["seed"],
                "python": platform.python_version(),
                "versions": {
                    n: version(n)
                    for n in ("torch", "transformers", "scikit-learn", "numpy", "peft")
                },
                "device": str(device),
                "lock_sha256": sha256(Path("uv.lock")),
            },
        )
    else:
        write_summary(
            args.output / "test.json",
            {
                **metadata,
                "selection_sha256": sha256(locked),
                "reference": "historical machine-assisted labels; gold_ready=false",
                "source": "SmartNotice Drive release split_65_15_20_v3_3_2026-11-15",
                "test_notices_sha256": sha256(args.split / "test/notices.jsonl"),
                "reference_sha256": sha256(
                    args.split / "reference_only_do_not_train_on_test/annotations.jsonl"
                ),
            },
        )
    print({n: s["event"]["f1"] for n, s in scores.items()})


if __name__ == "__main__":
    main()
