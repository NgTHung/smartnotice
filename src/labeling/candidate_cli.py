"""Provide local training, held-out evaluation and inference for span candidates."""

import argparse
import json
import pickle
import platform
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import scipy
import sklearn
from smartnotice import schemas
from smartnotice.io import write_jsonl
from smartnotice.labeling import (
    candidate_data,
    candidate_experiment,
    candidate_features,
    candidate_generation,
    candidate_metrics,
    candidates,
)
from smartnotice.labeling.candidate_data import HOLDOUTS, CandidateCorpus, file_sha256
from smartnotice.labeling.candidate_experiment import (
    evaluate_candidate_filters,
    predict_candidate_filters,
    train_candidate_filters,
)
from smartnotice.preprocessing import dates, links, text
from smartnotice.preprocessing.split import DEFAULT_SEED

_ARTIFACT_VERSION = 1
_MODULES = (
    candidate_data,
    candidate_experiment,
    candidate_features,
    candidate_generation,
    candidate_metrics,
    candidates,
    dates,
    links,
    schemas,
    text,
)


def _environment():
    lock = Path("uv.lock")
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
        "uv_lock_sha256": file_sha256(lock) if lock.is_file() else None,
        "module_hashes": {
            module.__name__: file_sha256(Path(module.__file__)) for module in _MODULES
        },
    }


def _write_report(output, report, predictions):
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_jsonl(output / "predictions.jsonl", predictions)


def _read_artifact(path):
    # The caller must supply a local artifact from the trusted training command.
    with path.open("rb") as file:
        artifact = pickle.load(file)
    if (
        artifact["artifact_version"] != _ARTIFACT_VERSION
        or artifact["generator_version"] != candidate_generation.GENERATOR_VERSION
        or artifact["environment"]["scikit_learn"] != sklearn.__version__
        or artifact["environment"]["module_hashes"] != _environment()["module_hashes"]
    ):
        raise ValueError(
            "Model artifact requires the same code and scikit-learn version as training"
        )
    return artifact


def _train(args):
    start = perf_counter()
    corpus = CandidateCorpus(args.snapshot, args.reviews, synthetic=args.synthetic)
    train, validation = (corpus.load(split) for split in candidate_data.DEVELOPMENT)
    artifact, results, predictions = train_candidate_filters(train, validation, args.seed)
    metadata = {
        "artifact_version": _ARTIFACT_VERSION,
        "generator_version": candidate_generation.GENERATOR_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "synthetic": args.synthetic,
        "environment": _environment(),
        "input_hashes": corpus.hashes,
        "split_counts": corpus.summary,
        "split_settings": {
            setting: sorted({row[setting] for row in corpus.assignments.values() if setting in row})
            for setting in ("seed", "similarity")
        },
        "elapsed_seconds": perf_counter() - start,
    }
    args.output.mkdir(parents=True, exist_ok=False)
    _write_report(args.output, {**metadata, **results, "checkpoint": "models.pkl"}, predictions)
    with (args.output / "models.pkl").open("xb") as file:
        pickle.dump({**artifact, **metadata, "development_groups": corpus.source_groups}, file)


def _evaluate(args):
    start = perf_counter()
    artifact = _read_artifact(args.models)
    corpus = CandidateCorpus(args.snapshot, args.reviews, synthetic=artifact["synthetic"])
    if corpus.hashes["assignments"] != artifact["input_hashes"]["assignments"]:
        raise ValueError("Held-out evaluation requires the exact frozen training assignments")
    corpus.source_groups.update(artifact["development_groups"])
    documents = corpus.load(args.split)
    metrics, predictions = evaluate_candidate_filters(artifact, documents)
    args.output.mkdir(parents=True, exist_ok=False)
    _write_report(
        args.output,
        {
            "split": args.split,
            "synthetic": artifact["synthetic"],
            "seed": artifact["seed"],
            "generator_version": artifact["generator_version"],
            "checkpoint_sha256": file_sha256(args.models),
            "input_hashes": corpus.hashes,
            "split_counts": corpus.summary,
            "environment": _environment(),
            "elapsed_seconds": perf_counter() - start,
            "metrics": metrics,
        },
        predictions,
    )


def _predict(args):
    artifact = _read_artifact(args.models)
    notices = list(candidate_data.read_candidate_notices(args.notices).values())
    predictions = predict_candidate_filters(artifact, notices)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        for row in predictions:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    """Run a candidate experiment command or exit with a safe input error."""
    parser = argparse.ArgumentParser(prog="smartnotice-candidates", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="Fit both filters and select thresholds on validation")
    train.add_argument("--seed", type=int, default=DEFAULT_SEED)
    train.add_argument("--synthetic", action="store_true", help="Require synthetic fixtures")
    evaluate = sub.add_parser("evaluate", help="Evaluate a frozen model on a named held-out split")
    evaluate.add_argument("--split", choices=HOLDOUTS, required=True)
    predict = sub.add_parser("predict", help="Score prepared notices with both filters")
    predict.add_argument("--notices", type=Path, required=True)
    for command in (train, evaluate):
        command.add_argument("--snapshot", type=Path, required=True)
        command.add_argument("--reviews", type=Path, required=True)
    for command in (evaluate, predict):
        command.add_argument(
            "--models", type=Path, required=True, help="Trusted local model artifact"
        )
    for command in (train, evaluate, predict):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        {"train": _train, "evaluate": _evaluate, "predict": _predict}[args.command](args)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"smartnotice-candidates: {exc}\n")
