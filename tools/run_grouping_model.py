"""Train and evaluate the SmartNotice binary event-identity baseline."""

import argparse
import hashlib
import json
import platform
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.grouping_model import (
    LEXICAL_THRESHOLD,
    fit_grouping_classifier,
    grouping_probability,
    pair_features,
    validate_grouping_mention,
)
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import (
    GroupFoldAssignment,
    GroupingLinearModel,
    GroupingModelMention,
    Notice,
)

LABELS = {"SAME_EVENT": True, "UPDATE_OF": True, "DIFFERENT_EVENT": False, "UNCLEAR": None}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _index(rows, field):
    indexed = {row[field]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate {field}")
    return indexed


def _load_cases(pairs_path, mentions_path, notices_path, assignments_path, split):
    assignments = {
        key: GroupFoldAssignment.model_validate(row)
        for key, row in _index(read_jsonl(assignments_path), "doc_id").items()
    }
    notices = {
        key: Notice.model_validate(row)
        for key, row in _index(read_jsonl(notices_path), "doc_id").items()
        if key in assignments and assignments[key].split == split
    }
    mentions = {}
    for key, row in _index(read_jsonl(mentions_path), "mention_id").items():
        mention = GroupingModelMention.model_validate(row)
        notice = notices.get(mention.doc_id)
        if notice is None:
            raise ValueError("Grouping example refers to a document outside its requested split")
        validate_grouping_mention(mention, notice)
        mentions[key] = mention
    cases = []
    seen = set()
    for rid, row in _index(read_jsonl(pairs_path), "review_id").items():
        if row["decision"] not in LABELS:
            raise ValueError(f"Unsupported decision for {rid}")
        left, right = mentions[row["left"]], mentions[row["right"]]
        key = frozenset((left.mention_id, right.mention_id))
        if len(key) != 2 or key in seen:
            raise ValueError(f"Duplicate relation for {rid}")
        seen.add(key)
        a, b = assignments[left.doc_id], assignments[right.doc_id]
        label = LABELS[row["decision"]]
        if split == "train":
            if a.fold is None or b.fold is None or label is None:
                raise ValueError(f"Missing train fold or label for {rid}")
            if (row["left_fold"], row["right_fold"], row["same_event"]) != (a.fold, b.fold, label):
                raise ValueError(f"Train metadata does not match the frozen release for {rid}")
            if label and a.fold != b.fold:
                raise ValueError(f"Positive training example crosses folds for {rid}")
        elif a.fold is not None or b.fold is not None:
            raise ValueError(f"Test document belongs to a training fold for {rid}")
        cases.append(
            {
                "review_id": rid,
                "left": left.mention_id,
                "right": right.mention_id,
                "label": label,
                "folds": [a.fold, b.fold],
                "groups": [a.group_id, b.group_id],
                "features": pair_features(left, right),
            }
        )
    return cases


def _fit(cases, seed):
    return fit_grouping_classifier(
        [c["features"] for c in cases], [c["label"] for c in cases], seed=seed
    )


def _predict(model, cases, fold=None):
    rows = []
    for case in cases:
        score = grouping_probability(model, case["features"])
        rows.append(
            {
                "review_id": case["review_id"],
                "left": case["left"],
                "right": case["right"],
                "validation_fold": fold,
                "same_event": case["label"],
                "grouping_score": score,
                "logistic_regression": score >= model.threshold,
                "lexical_baseline": case["features"][0] >= LEXICAL_THRESHOLD,
                "always_different": False,
            }
        )
    return rows


def _metrics(predictions):
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
    )

    scored = [p for p in predictions if p["same_event"] is not None]
    labels = [p["same_event"] for p in scored]
    result = {
        "scored": len(labels),
        "positive": sum(labels),
        "unresolved": len(predictions) - len(labels),
    }
    for column in ("logistic_regression", "lexical_baseline", "always_different"):
        observed = [p[column] for p in scored]
        both = set(labels) == {False, True}
        result[column] = {
            "accuracy": accuracy_score(labels, observed) if labels else None,
            "positive_precision": precision_score(labels, observed, zero_division=0)
            if any(observed)
            else None,
            "positive_recall": recall_score(labels, observed) if any(labels) else None,
            "positive_f1": f1_score(labels, observed, zero_division=0) if any(labels) else None,
            "macro_f1": f1_score(labels, observed, average="macro", zero_division=0)
            if both
            else None,
            "confusion_negative_positive": confusion_matrix(
                labels, observed, labels=[False, True]
            ).tolist()
            if labels
            else [[0, 0], [0, 0]],
        }
    result["logistic_regression"]["average_precision"] = (
        average_precision_score(labels, [p["grouping_score"] for p in scored])
        if set(labels) == {False, True}
        else None
    )
    return result


def _train(args):
    dataset = args.dataset
    files = [dataset / "train" / f"{key}.jsonl" for key in ("pairs", "mentions", "notices")]
    files.append(dataset / "fold_assignments.jsonl")
    checksums = json.loads((dataset / "checksums.json").read_bytes())
    for file in files:
        if _sha(file) != checksums.get(file.relative_to(dataset).as_posix()):
            raise ValueError(f"Training dataset checksum mismatch: {file.name}")
    cases = _load_cases(*files, "train")
    folds = sorted({f for c in cases for f in c["folds"]})
    predictions = []
    counts = []
    for i in folds:
        fit = [c for c in cases if i not in c["folds"]]
        validation = [c for c in cases if c["folds"] == [i, i]]
        fit_groups = {group for c in fit for group in c["groups"]}
        valid_groups = {group for c in validation for group in c["groups"]}
        if fit_groups & valid_groups:
            raise ValueError(f"Evaluation groups overlap in fold {i}")
        model = _fit(fit, args.seed)
        forecasts = _predict(model, validation, i)
        predictions.extend(forecasts)
        counts.append(
            {
                "fold": i,
                "fit": len(fit),
                "omitted": len(cases) - len(fit) - len(validation),
                "metrics": _metrics(forecasts),
            }
        )
    summary = {
        "kind": "grouping_training_development_cv",
        "seed": args.seed,
        "optimizer": {"C": 1.0, "solver": "lbfgs", "max_iter": 1000},
        "lexical_threshold": LEXICAL_THRESHOLD,
        "train_pairs": len(cases),
        "out_of_fold": _metrics(predictions),
        "folds": counts,
    }
    return summary, predictions, _fit(cases, args.seed), [*files, dataset / "checksums.json"]


def _evaluate(args):
    files = [
        args.reviewed_holdout / "pairs.jsonl",
        args.reviewed_holdout / "mentions.jsonl",
        args.test_notices,
        args.dataset / "fold_assignments.jsonl",
    ]
    cases = _load_cases(*files, "test")
    checkpoint = args.model_dir / "model.json"
    training = json.loads((args.model_dir / "run.json").read_bytes())
    if training["model_sha256"] != _sha(checkpoint):
        raise ValueError("Model differs from its training manifest")
    if training["inputs_sha256"].get(files[3].as_posix()) != _sha(files[3]):
        raise ValueError("Holdout and model use different frozen assignments")
    model = GroupingLinearModel.model_validate_json(checkpoint.read_bytes())
    predictions = _predict(model, cases)
    summary = {
        "kind": "grouping_assistant_reviewed_email_holdout",
        "metrics": _metrics(predictions),
        "independent_human_gold": False,
        "sampling_record": str(args.reviewed_holdout / "selection.json"),
    }
    return (
        summary,
        predictions,
        None,
        [
            *files,
            checkpoint,
            args.model_dir / "run.json",
            args.reviewed_holdout / "selection.json",
        ],
    )


def main() -> None:
    """Write aggregate metrics and private pair predictions for the requested phase."""
    import sklearn

    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--seed", type=int, default=DEFAULT_SEED)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--reviewed-holdout", type=Path, required=True)
    evaluate.add_argument("--test-notices", type=Path, required=True)
    evaluate.add_argument("--model-dir", type=Path, required=True)
    for command in (train, evaluate):
        command.add_argument("--dataset", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
    args = cli.parse_args()
    output = args.output_dir.resolve()
    root = Path("reports/generated").resolve()
    if output == root or not output.is_relative_to(root) or output.exists():
        cli.error("Choose a new directory under reports/generated")
    summary, predictions, model, sources = (_train if args.command == "train" else _evaluate)(args)
    provenance = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scikit_learn": sklearn.__version__,
        "inputs_sha256": {
            p.as_posix(): _sha(p)
            for p in [
                *sources,
                Path(__file__),
                Path("src/labeling/grouping_model.py"),
                Path("uv.lock"),
            ]
        },
    }
    output.mkdir(parents=True, exist_ok=False)
    if model is not None:
        _json(output / "model.json", model.model_dump(mode="json"))
        provenance["model_sha256"] = _sha(output / "model.json")
    write_jsonl(output / "predictions.jsonl", predictions)
    _json(output / "run.json", {**summary, **provenance})
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
