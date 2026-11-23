"""Re-evaluate saved BamiBERT weights with same-type span overlap suppression."""

import argparse
import json
import random
from dataclasses import replace
from pathlib import Path

import torch
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.modeling.applicability import LABELS, build_examples, propagated_scores
from smartnotice.modeling.data import load_development, sha256, tokenize
from smartnotice.modeling.experiment import (
    Settings,
    configure_encoder,
    evaluate_extraction,
    load_extractor,
    restore_weights,
    write_summary,
)
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def main() -> None:
    """Reload both task checkpoints and write a separate development score record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads((args.run / "run.json").read_text(encoding="utf-8"))
    if sha256(args.checkpoint / "model.safetensors") != metadata["model_weights_sha256"]:
        raise ValueError("Base model differs from the training run")
    documents, provenance = load_development(args.split)
    if provenance["hashes"] != metadata["data"]["hashes"]:
        raise ValueError("Data files differ from the training run")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    settings = replace(Settings(**metadata["settings"]), suppress_same_type_overlap=True)
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint, use_fast=True)
    extraction_path = args.run / "extraction.pt"
    checkpoint = torch.load(extraction_path, map_location="cpu")
    model = load_extractor(args.checkpoint, checkpoint, tokenizer.pad_token_id, settings, device)
    tokenized = [
        tokenize(doc, tokenizer, settings.length, settings.overlap, checkpoint["width"])
        for doc in documents["validation"]
    ]
    extraction, predictions = evaluate_extraction(model, tokenized, settings)
    del model

    rng = random.Random(settings.seed)
    profiles = generate_profiles(
        [c for doc in documents["train"] for c in doc.annotation.audience_constraints],
        settings.seed,
    )
    panel = rng.sample(profiles, min(settings.app_eval_profiles, len(profiles)))
    rows = build_examples(documents["validation"], panel, rng)
    app_path = args.run / "applicability.pt"
    app = AutoModelForSequenceClassification.from_pretrained(
        args.checkpoint,
        num_labels=len(LABELS),
        label2id={label: i for i, label in enumerate(LABELS)},
        id2label=dict(enumerate(LABELS)),
    )
    configure_encoder(app.base_model, settings)
    restore_weights(app, torch.load(app_path, map_location="cpu"), settings)
    applicability = propagated_scores(
        app.to(device),
        tokenizer,
        documents["validation"],
        rows,
        predictions,
        panel,
        settings,
        device,
    )
    result = {
        "suppression": "greedy same-type overlap suppression in descending span score order",
        "extraction_sha256": sha256(extraction_path),
        "applicability_sha256": sha256(app_path),
        "extraction": extraction,
        "applicability_on_predicted_events": applicability,
    }
    write_summary(args.run / "overlap_suppression_metrics.json", result)
    print("Replayed both checkpoints and saved overlap suppression metrics")


if __name__ == "__main__":
    main()
