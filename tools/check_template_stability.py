"""Check the selected extractor across grouped development folds and training seeds."""

import argparse
import json
from pathlib import Path
from statistics import mean, stdev

from compare_notice_pipelines import _context_predictions, _metrics
from sklearn.model_selection import GroupKFold
from smartnotice.modeling.contextual import (
    ContextExtractor,
    DocumentTemplateExtractor,
    TemplateExtractor,
)
from smartnotice.modeling.data import load_development, sha256
from smartnotice.modeling.experiment import write_summary


def _evaluate(train, validation, seed, cutoff):
    tagger = ContextExtractor(seed)
    tagger.fit(train)
    sentences = TemplateExtractor(tagger, 0.65)
    sentences.fit(train)
    documents = DocumentTemplateExtractor(sentences, 0.60)
    documents.fit(train)
    predictions = _context_predictions(documents, validation, (cutoff,))[cutoff]
    metrics = _metrics(validation, predictions)
    return {
        "seed": seed,
        "train_documents": len(train),
        "scored_documents": len(validation),
        "validation_groups": sorted({d.group_id for d in validation}),
        "span": metrics["span"]["micro"],
        "link": metrics["link"]["micro"],
        "event": metrics["event"],
    }


def main() -> None:
    """Refit all learned extraction stages using only the training groups of each fold."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    locked = args.run / "selected.json"
    config = json.loads(locked.read_text(encoding="utf-8"))
    docs, provenance = load_development(args.split)
    if config["development_hashes"] != provenance["hashes"] or config["winner"] != "documents":
        raise ValueError("Development release or selected extractor differs")
    path = args.run / "stability.json"
    result = {"selection_sha256": sha256(locked), "folds": [], "seeds": []}
    cutoff = config["link_cutoffs"]["documents"]
    pool = docs["train"] + docs["validation"]
    folds = GroupKFold(n_splits=5).split(pool, groups=[d.group_id for d in pool])
    for train, val in folds:
        row = _evaluate([pool[i] for i in train], [pool[i] for i in val], config["seed"], cutoff)
        result["folds"].append(row)
        write_summary(path, result)
        print("Completed fold", len(result["folds"]), flush=True)
    validation = json.loads((args.run / "validation.json").read_text(encoding="utf-8"))["scores"][
        "documents"
    ]
    result["seeds"].append(
        {
            "seed": config["seed"],
            "span": validation["span"]["micro"],
            "link": validation["link"]["micro"],
            "event": validation["event"],
        }
    )
    for seed in (config["seed"] + 1, config["seed"] + 2):
        result["seeds"].append(_evaluate(docs["train"], docs["validation"], seed, cutoff))
        write_summary(path, result)
    for subset in ("folds", "seeds"):
        result[subset + "_summary"] = {}
        for metric in ("span", "link", "event"):
            scores = [row[metric]["f1"] for row in result[subset]]
            result[subset + "_summary"][metric] = {
                "mean_f1": mean(scores),
                "sample_sd": stdev(scores),
            }
    write_summary(path, result)


if __name__ == "__main__":
    main()
