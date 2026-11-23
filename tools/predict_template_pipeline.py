"""Predict events from prepared notices with the frozen document-template pipeline."""

import argparse
import json
from pathlib import Path

import joblib
import torch
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.modeling.applicability import LABELS, event_context, predict_logits, profile_text
from smartnotice.modeling.data import sha256
from smartnotice.modeling.experiment import Settings, configure_encoder, restore_weights
from smartnotice.modeling.extraction import decode_notice
from smartnotice.schemas import Notice, Profile
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def main() -> None:
    """Write predicted annotations and, when supplied a profile, one label per predicted event."""
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run", "notices", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    for key in ("profile", "base", "baseline"):
        parser.add_argument(f"--{key}", type=Path)
    args = parser.parse_args()
    if args.profile and not (args.base and args.baseline):
        parser.error("--profile requires --base and --baseline")
    config = json.loads((args.run / "selected.json").read_text(encoding="utf-8"))
    path = args.run / "documents.joblib"
    if config["winner"] != "documents" or sha256(path) != config["hashes"]["documents"]:
        raise ValueError("Expected the selected document-template checkpoint")
    extractor = joblib.load(path)
    profile = None
    if args.profile:
        profile = Profile.model_validate_json(args.profile.read_bytes())
        for name, file in {
            "base": args.base / "model.safetensors",
            "tokenizer": args.base / "tokenizer.json",
            "app": args.baseline / "applicability.pt",
        }.items():
            if sha256(file) != config["hashes"][name]:
                raise ValueError(f"Unexpected checkpoint hash for {name}")
        settings = Settings(
            **json.loads((args.baseline / "run.json").read_text(encoding="utf-8"))["settings"]
        )
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        tokenizer = AutoTokenizer.from_pretrained(args.base, use_fast=True)
        model = AutoModelForSequenceClassification.from_pretrained(
            args.base,
            num_labels=len(LABELS),
            label2id={v: i for i, v in enumerate(LABELS)},
            id2label=dict(enumerate(LABELS)),
        )
        configure_encoder(model.base_model, settings)
        restore_weights(
            model, torch.load(args.baseline / "applicability.pt", map_location="cpu"), settings
        )
        model.to(device)
    annotations, applications = [], []
    for row in read_jsonl(args.notices):
        notice = Notice.model_validate(row)
        spans, scored = extractor.candidates(notice)
        links = {key for key, prob in scored if prob >= config["link_cutoffs"]["documents"]}
        ann = decode_notice(notice, spans, links, "context-prediction")
        annotations.append(ann.model_dump(mode="json"))
        if profile:
            rows = [
                {
                    "context": event_context(notice, ann, event),
                    "profile": profile_text(profile.model_dump()),
                }
                for event in ann.events
            ]
            logits = predict_logits(model, tokenizer, rows, settings.length, device)
            for event, idx in zip(ann.events, logits.argmax(dim=1).tolist(), strict=True):
                applications.append(
                    {
                        "doc_id": notice.doc_id,
                        "event_id": event.event_id,
                        "profile_id": profile.profile_id,
                        "label": LABELS[idx],
                    }
                )
    args.output.mkdir(parents=True, exist_ok=False)
    write_jsonl(args.output / "events.jsonl", annotations)
    if profile:
        write_jsonl(args.output / "applicability.jsonl", applications)


if __name__ == "__main__":
    main()
