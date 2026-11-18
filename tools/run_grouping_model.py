"""Train and evaluate the SmartNotice binary event-identity baseline."""

import argparse
import hashlib
import json
import platform
from dataclasses import asdict
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.grouping_academic import academic_scope, apply_academic_scope
from smartnotice.labeling.grouping_evidence import compare_pair_evidence, evidence_decision
from smartnotice.labeling.grouping_followup import (
    followup_evidence,
    load_email_routing,
    resolve_followup,
)
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
KINDS = {"baseline": "grouping-logistic-v1", "evidence": "grouping-logistic-v2"}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _index(rows, field):
    indexed = {row[field]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate {field}")
    return indexed


def _load_cases(
    pairs_path,
    mentions_path,
    notices_path,
    assignments_path,
    split,
    kind,
    *,
    fitting=True,
    raw_email_dir=None,
    use_academic_scope=False,
    resolve_relations=False,
):
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
    headers = (
        {
            key: load_email_routing(notices[key], raw_email_dir)
            for key in {mention.doc_id for mention in mentions.values()}
        }
        if raw_email_dir is not None
        else {}
    )
    scoped = (
        {
            key: academic_scope(m, notices[m.doc_id], headers.get(m.doc_id))
            for key, m in mentions.items()
        }
        if use_academic_scope
        else {}
    )
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
        update_side = row.get("update_side")
        if update_side is not None and (
            type(update_side) is not int
            or update_side not in (0, 1)
            or row["decision"] != "UPDATE_OF"
        ):
            raise ValueError(f"Invalid update direction for {rid}")
        if fitting:
            if a.fold is None or b.fold is None or label is None:
                raise ValueError(f"Missing train fold or label for {rid}")
            if (row["left_doc_id"], row["right_doc_id"]) != (left.doc_id, right.doc_id):
                raise ValueError(f"Train document IDs differ from their source mentions for {rid}")
            if (row["left_fold"], row["right_fold"], row["same_event"]) != (a.fold, b.fold, label):
                raise ValueError(f"Train metadata does not match the frozen release for {rid}")
            if label and a.fold != b.fold:
                raise ValueError(f"Positive training example crosses folds for {rid}")
        elif split != "train" and (a.fold is not None or b.fold is not None):
            raise ValueError(f"Evaluation document belongs to a training fold for {rid}")
        features = pair_features(left, right)
        evidence = None
        followup = None
        if kind == KINDS["evidence"]:
            evidence = compare_pair_evidence(
                left, right, notices[left.doc_id], notices[right.doc_id]
            )
            features += evidence.features
            if raw_email_dir is not None:
                followup = followup_evidence(
                    left,
                    right,
                    (notices[left.doc_id], notices[right.doc_id]),
                    (headers[left.doc_id], headers[right.doc_id]),
                    evidence,
                )
        cases.append(
            {
                "review_id": rid,
                "left": left.mention_id,
                "right": right.mention_id,
                "label": label,
                "folds": [a.fold, b.fold],
                "groups": [a.group_id, b.group_id],
                "fold_groups": [a.fold_group_id, b.fold_group_id],
                "features": features,
                "evidence": evidence,
                "followup": followup,
                "academic_scopes": (scoped[left.mention_id], scoped[right.mention_id])
                if scoped
                else None,
                "relation_inputs": (left, right, (notices[left.doc_id], notices[right.doc_id]))
                if resolve_relations
                else None,
                "reference_relation": (row["decision"], update_side) if resolve_relations else None,
                "stratum": row.get("stratum", "unspecified"),
            }
        )
    return cases


def _fit(cases, seed, kind):
    return fit_grouping_classifier(
        [c["features"] for c in cases], [c["label"] for c in cases], seed=seed, kind=kind
    )


def _predict(model, cases, fold=None):
    rows = []
    for case in cases:
        score = grouping_probability(model, case["features"])
        row = {
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
        if case["evidence"] is not None:
            evidence = case["evidence"]
            status = evidence_decision(score, model.threshold, evidence)
            row["ungated_logistic"] = row["logistic_regression"]
            row["logistic_regression"] = status == "SAME_EVENT"
            row["decision"] = status
            row["anchor"] = evidence.anchor
        if case["followup"] is not None:
            followup = case["followup"]
            row["followup_title"] = row["logistic_regression"] or followup.title
            row["followup_reference"] = row["logistic_regression"] or followup.reference
            row["followup_combined"] = row["logistic_regression"] or followup.joint
            row["followup_evidence"] = asdict(followup)
            if case["academic_scopes"] is not None:
                base = "SAME_EVENT" if row["followup_combined"] else row["decision"]
                refined = apply_academic_scope(*case["academic_scopes"], followup.routing, base)
                row["academic_scope"] = refined.decision in ("SAME_EVENT", "UPDATE_OF")
                row["academic_decision"] = asdict(refined)
            if case["relation_inputs"] is not None:
                base = "SAME_EVENT" if row["followup_combined"] else row["decision"]
                relation = resolve_followup(*case["relation_inputs"], evidence, followup, base)
                decision = relation.decision
                scope_reason = None
                if case["academic_scopes"] is not None:
                    scoped = apply_academic_scope(
                        *case["academic_scopes"],
                        followup.routing,
                        "SAME_EVENT" if decision == "UPDATE_OF" else decision,
                    )
                    qualified_change = (
                        decision == "UPDATE_OF" and scoped.reason == "different_dates_same_role"
                    )
                    if scoped.decision in ("DIFFERENT_EVENT", "UNCLEAR") and not qualified_change:
                        decision = scoped.decision
                        if scoped.reason != "base":
                            scope_reason = scoped.reason
                row["resolved_followup"] = decision in ("SAME_EVENT", "UPDATE_OF")
                row["followup_relation"] = {"evidence": asdict(relation), "decision": decision}
                if scope_reason is not None:
                    row["followup_relation"]["scope_reason"] = scope_reason
                row["reference_decision"], row["reference_update_side"] = case["reference_relation"]
                row["stratum"] = case["stratum"]
        rows.append(row)
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
    columns = ["logistic_regression", "lexical_baseline", "always_different"]
    if predictions and "ungated_logistic" in predictions[0]:
        columns.append("ungated_logistic")
        result["evidence_policy"] = {
            "decided": sum(p["decision"] != "UNCLEAR" for p in scored),
            "withheld_labeled_positive": sum(
                p["decision"] == "UNCLEAR" and p["same_event"] for p in scored
            ),
            "withheld_labeled_negative": sum(
                p["decision"] == "UNCLEAR" and not p["same_event"] for p in scored
            ),
        }
    if predictions and "followup_combined" in predictions[0]:
        columns.extend(("followup_title", "followup_reference", "followup_combined"))
    if predictions and "academic_scope" in predictions[0]:
        columns.append("academic_scope")
        result["academic_review"] = {
            "unclear_labeled_positive": sum(
                p["academic_decision"]["decision"] == "UNCLEAR" and p["same_event"] for p in scored
            ),
            "unclear_labeled_negative": sum(
                p["academic_decision"]["decision"] == "UNCLEAR" and not p["same_event"]
                for p in scored
            ),
        }
    if predictions and "resolved_followup" in predictions[0]:
        columns.append("resolved_followup")
        updates = [p for p in predictions if p["reference_decision"] == "UPDATE_OF"]
        result["followup_relation"] = {
            "exact_labels": sum(
                p["followup_relation"]["decision"] == p["reference_decision"] for p in predictions
            ),
            "reference_updates": len(updates),
            "predicted_updates": sum(
                p["followup_relation"]["decision"] == "UPDATE_OF" for p in predictions
            ),
            "correct_update_labels": sum(
                p["followup_relation"]["decision"] == "UPDATE_OF" for p in updates
            ),
            "reference_directed_updates": sum(
                p["reference_update_side"] in (0, 1) for p in updates
            ),
            "correct_directed_updates": sum(
                p["followup_relation"]["decision"] == "UPDATE_OF"
                and p["reference_update_side"] in (0, 1)
                and p["followup_relation"]["evidence"]["update_side"] == p["reference_update_side"]
                for p in updates
            ),
        }
    for column in columns:
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
    ranking = "ungated_logistic" if "ungated_logistic" in columns else "logistic_regression"
    result[ranking]["average_precision"] = (
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
    kind = KINDS[args.variant]
    cases = _load_cases(*files, "train", kind)
    folds = sorted({f for c in cases for f in c["folds"]})
    predictions = []
    counts = []
    for i in folds:
        fit = [c for c in cases if i not in c["folds"]]
        validation = [c for c in cases if c["folds"] == [i, i]]
        fit_groups = {group for c in fit for group in c["groups"]}
        valid_groups = {group for c in validation for group in c["groups"]}
        fit_components = {group for c in fit for group in c["fold_groups"]}
        valid_components = {group for c in validation for group in c["fold_groups"]}
        if fit_groups & valid_groups or fit_components & valid_components:
            raise ValueError(f"Evaluation groups overlap in fold {i}")
        model = _fit(fit, args.seed, kind)
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
        "model_kind": kind,
        "seed": args.seed,
        "optimizer": {"C": 1.0, "solver": "lbfgs", "max_iter": 1000},
        "lexical_threshold": LEXICAL_THRESHOLD,
        "train_pairs": len(cases),
        "out_of_fold": _metrics(predictions),
        "folds": counts,
    }
    return summary, predictions, _fit(cases, args.seed, kind), [*files, dataset / "checksums.json"]


def _evaluate(args):
    files = [
        args.reviewed_holdout / "pairs.jsonl",
        args.reviewed_holdout / "mentions.jsonl",
        args.test_notices,
        args.dataset / "fold_assignments.jsonl",
    ]
    checkpoint = args.model_dir / "model.json"
    training = json.loads((args.model_dir / "run.json").read_bytes())
    if training["model_sha256"] != _sha(checkpoint):
        raise ValueError("Model differs from its training manifest")
    if training["inputs_sha256"].get(files[3].as_posix()) != _sha(files[3]):
        raise ValueError("Holdout and model use different frozen assignments")
    model = GroupingLinearModel.model_validate_json(checkpoint.read_bytes())
    if args.raw_email_dir is not None and model.kind != KINDS["evidence"]:
        raise ValueError("Follow-up evaluation requires an evidence checkpoint")
    cases = _load_cases(
        *files,
        args.evaluation_split,
        model.kind,
        fitting=False,
        raw_email_dir=args.raw_email_dir,
        use_academic_scope=args.academic_scope,
        resolve_relations=args.resolve_followup,
    )
    if args.evaluation_split == "train":
        train_pairs = args.dataset / "train/pairs.jsonl"
        if training["inputs_sha256"].get(train_pairs.as_posix()) != _sha(train_pairs):
            raise ValueError("Challenge and model use different fitting pairs")
        assignments = _index(read_jsonl(files[3]), "doc_id")
        train_docs = {
            r[f"{side}_doc_id"] for r in read_jsonl(train_pairs) for side in ("left", "right")
        }
        train_groups = {assignments[did]["group_id"] for did in train_docs}
        train_components = {assignments[did]["fold_group_id"] for did in train_docs}
        if any(
            train_groups.intersection(case["groups"])
            or train_components.intersection(case["fold_groups"])
            for case in cases
        ):
            raise ValueError("Challenge pairs share a frozen group with fitting examples")
        files.append(train_pairs)
    predictions = _predict(model, cases)
    summary = {
        "kind": "grouping_assistant_reviewed_email_holdout",
        "model_kind": model.kind,
        "evaluation_split": args.evaluation_split,
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
    train.add_argument("--variant", choices=KINDS, default="baseline")
    train.add_argument("--seed", type=int, default=DEFAULT_SEED)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--reviewed-holdout", type=Path, required=True)
    evaluate.add_argument("--test-notices", type=Path, required=True)
    evaluate.add_argument(
        "--evaluation-split", choices=("test", "validation", "train"), default="test"
    )
    evaluate.add_argument("--raw-email-dir", type=Path)
    evaluate.add_argument("--academic-scope", action="store_true")
    evaluate.add_argument("--resolve-followup", action="store_true")
    evaluate.add_argument("--model-dir", type=Path, required=True)
    for command in (train, evaluate):
        command.add_argument("--dataset", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
    args = cli.parse_args()
    if args.command == "evaluate" and args.raw_email_dir and not args.raw_email_dir.is_dir():
        cli.error("The raw email directory does not exist")
    if args.command == "evaluate" and args.raw_email_dir is None:
        if args.academic_scope or args.resolve_followup:
            cli.error("Academic-scope and follow-up relation comparisons require --raw-email-dir")
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
                Path("src/labeling/grouping_evidence.py"),
                Path("src/labeling/grouping_academic.py"),
                Path("src/labeling/grouping_followup.py"),
                Path("src/parsers/email.py"),
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
