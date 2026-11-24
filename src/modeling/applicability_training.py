"""Train LightGBM applicability models on grouped train/validation pairs."""

import json
import math
import platform
import subprocess
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import file_digest, sha256
from importlib.metadata import version
from pathlib import Path
from random import Random
from typing import Annotated, Literal, TextIO

import numpy as np
from lightgbm import LGBMClassifier
from lightgbm.basic import LightGBMError
from pydantic import Field, ValidationError, model_validator
from sklearn.model_selection import GroupKFold
from smartnotice.io import write_jsonl
from smartnotice.modeling.applicability_features import (
    ApplicabilityInput,
    AudienceSource,
    FeatureBuilder,
    build_inputs,
)
from smartnotice.modeling.lexicon import DEFAULT_LEXICON_PATH, Lexicon, load_lexicon
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import Annotation, Notice, Record

_DEFAULT_OUTPUT_ROOT = Path("reports/generated/applicability")
_LABELS = ("APPLIES", "NOT_APPLIES", "UNCLEAR")
_LABEL_INDEX = {label: i for i, label in enumerate(_LABELS)}
_LABEL_ORIGIN = "constraint_rule"
_AUDIENCE_POLICY = "assume_all_students_without_audience"
_SOURCES = ("email", "web")
_POOL_SPLITS = {"train", "validation"}
_HELD_OUT_SPLITS = {"test", "domain_test", "excluded"}
_REASON_SLICES = {
    "exclusion": {"excluded_status"},
    "implicit_audience": {"implicit_audience"},
    "missing_audience": {"no_audience_constraint", "assumed_all_students_no_audience"},
    "condition": {"unmodeled_condition"},
}
_MISMATCH_REASONS = tuple(
    f"mismatched_{field}" for field in ("cohort", "degree_level", "major", "program", "status")
)
_DEFAULT_PARAMS = {
    "boosting_type": "gbdt",
    "n_estimators": 100,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 20,
    "n_jobs": 1,
    "deterministic": True,
    "force_col_wise": True,
    "verbosity": -1,
}
_RESERVED_PARAMS = {
    "objective",
    "objective_type",
    "app",
    "application",
    "loss",
    "num_class",
    "num_classes",
    "random_state",
    "random_seed",
    "seed",
}
_RUN_FILES = (
    "record.json",
    "folds.jsonl",
    "oof_predictions.jsonl",
    "metrics.json",
    "feature_names.json",
    "importances.json",
    "model.txt",
    "tfidf.json",
)
Seed = Annotated[int, Field(ge=0, le=2**31 - 1)]
Fraction = Annotated[float, Field(gt=0, le=1)]


class TrainingConfig(Record):
    """Configure grouped cross-validation, training filters, and optional refit."""

    audience_source: AudienceSource
    train_sources: list[Literal["email", "web"]] = Field(
        default_factory=lambda: list(_SOURCES), min_length=1
    )
    learning_curve: Annotated[list[Fraction], Field(min_length=1)] | None = None
    seeds: list[Seed] = Field(
        default_factory=lambda: [DEFAULT_SEED + offset for offset in range(3)], min_length=1
    )
    folds: int = Field(default=5, ge=2)
    tfidf: bool = True
    source_feature: bool = True
    weighting: Literal["event", "pair"] = "event"
    params: dict = Field(default_factory=dict)
    param_grid: Annotated[list[dict], Field(min_length=1)] | None = None
    fit_final: bool = False
    allow_synthetic: bool = False

    @model_validator(mode="after")
    def _validate_options(self) -> "TrainingConfig":
        for name in ("seeds", "train_sources", "learning_curve"):
            values = getattr(self, name)
            if values is not None and len(set(values)) != len(values):
                raise ValueError(f"{name} must not contain duplicates")
        if self.learning_curve is not None and "web" not in self.train_sources:
            raise ValueError("learning_curve requires web in train_sources")
        for params in [self.params, *(self.param_grid or [])]:
            if protected := _RESERVED_PARAMS.intersection(params):
                raise ValueError(f"Training sets the LightGBM parameters {sorted(protected)}")
        return self


def load_pool(
    pairs: list[dict], assignments: list[dict], *, allow_synthetic: bool = False
) -> tuple[list[dict], str | None]:
    """Join rows to allowed document groups and return their audience policy.

    Reject missing assignments, held-out pairs, and mixed policy rows before
    excluding synthetic pairs. Leave the input rows unchanged.
    """
    by_doc = {}
    held_out_groups = set()
    for line, row in enumerate(assignments, 1):
        doc_id, group, split = row.get("doc_id"), row.get("group_id"), row.get("split")
        if not isinstance(doc_id, str) or not doc_id or not isinstance(group, str) or not group:
            raise ValueError(
                f"assignment line {line}: doc_id and group_id must be nonempty strings"
            )
        if doc_id in by_doc:
            raise ValueError(f"assignment line {line}: duplicate document ID {doc_id}")
        if not isinstance(split, str) or split not in _POOL_SPLITS | _HELD_OUT_SPLITS:
            raise ValueError(f"assignment line {line}: invalid split")
        by_doc[doc_id] = (split, group)
        if split in _HELD_OUT_SPLITS:
            held_out_groups.add(group)

    policies = set()
    pool = []
    for line, pair in enumerate(pairs, 1):
        doc_id = pair.get("doc_id")
        if not isinstance(doc_id, str) or doc_id not in by_doc:
            raise ValueError(f"pair line {line}: no document split assignment")
        split, group = by_doc[doc_id]
        if split not in _POOL_SPLITS:
            raise ValueError(f"pair line {line}: document {doc_id} has disallowed split {split}")
        if group in held_out_groups:
            raise ValueError(f"pair line {line}: group {group} also has a held-out assignment")
        if "audience_policy" in pair and pair["audience_policy"] != _AUDIENCE_POLICY:
            raise ValueError(f"pair line {line}: unknown audience_policy")
        policies.add(pair.get("audience_policy"))
        if len(policies) > 1:
            raise ValueError(f"pair line {line}: mixed missing-audience policy (audience_policy)")
        synthetic = pair.get("synthetic", False)
        if not isinstance(synthetic, bool):
            raise ValueError(f"pair line {line}: synthetic must be a boolean")
        if allow_synthetic or not synthetic:
            pool.append(pair | {"split": split, "group_id": group})
    return pool, next(iter(policies), None)


def assign_folds(group_ids: list[str], folds: int, seed: int) -> dict[str, int]:
    """Map each group to its zero-based held-out fold using the full pool."""
    count = len(set(group_ids))
    if not 2 <= folds <= count:
        raise ValueError(f"GroupKFold needs 2 to {count} folds for the available groups")
    groups = np.asarray(group_ids)
    mapping = {}
    splitter = GroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    for fold, (_, held_out) in enumerate(splitter.split(groups, groups=groups)):
        for group in np.unique(groups[held_out]).tolist():
            if group in mapping:
                raise ValueError(f"Group {group} crosses GroupKFold folds")
            mapping[group] = fold
    return mapping


def web_group_subsets(
    groups: list[str], fractions: list[float], seed: int
) -> dict[float, set[str]]:
    """Sample nested prefixes of a seeded group order, rounding counts up."""
    if any(not 0 < fraction <= 1 for fraction in fractions):
        raise ValueError("Learning-curve fractions must be in (0, 1]")
    ordered = sorted(set(groups))
    Random(seed).shuffle(ordered)
    return {
        fraction: set(ordered[: math.ceil(fraction * len(ordered))])
        for fraction in sorted(fractions)
    }


def event_weights(keys: Sequence[tuple[str, str]]) -> np.ndarray:
    """Return pair weights that sum to one for each document/event key."""
    counts = Counter(keys)
    return np.array([1 / counts[key] for key in keys], dtype=float)


def compute_metrics(
    gold: Sequence[str] | np.ndarray,
    pred: Sequence[str] | np.ndarray,
    weights: Sequence[float] | np.ndarray,
) -> dict:
    """Score weighted predictions in fixed label order with zero absent-class scores.

    The confusion matrix has gold rows and predicted columns. Supports and
    total weight use the supplied weights. n_pairs is the unweighted row count.
    """
    if len(gold) != len(pred) or len(gold) != len(weights):
        raise ValueError("Gold labels, predictions, and weights must have equal lengths")
    try:
        gold_ids = np.array([_LABEL_INDEX[label] for label in gold], dtype=np.intp)
        pred_ids = np.array([_LABEL_INDEX[label] for label in pred], dtype=np.intp)
    except KeyError:
        raise ValueError("Metrics require labels from the applicability contract") from None
    return _label_metrics(gold_ids, pred_ids, np.asarray(weights, dtype=float))


def _label_metrics(gold: np.ndarray, pred: np.ndarray, weights: np.ndarray) -> dict:
    size = len(_LABELS)
    bins = np.bincount(size * gold + pred, weights=weights, minlength=size**2)
    matrix = bins.reshape(size, size)
    gold_support = matrix.sum(axis=1)
    predicted_support = matrix.sum(axis=0)
    correct = matrix.diagonal()
    precision = np.divide(correct, predicted_support, out=np.zeros(3), where=predicted_support > 0)
    recall = np.divide(correct, gold_support, out=np.zeros(3), where=gold_support > 0)
    support_sum = gold_support + predicted_support
    f1 = np.divide(2 * correct, support_sum, out=np.zeros(3), where=support_sum > 0)
    return {
        "n_pairs": len(gold),
        "weight": float(gold_support.sum()),
        "macro_f1": float(f1.mean()),
        "applies_recall": float(recall[0]),
        "confusion_matrix": matrix.tolist(),
        "per_class": {
            label: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": float(gold_support[i]),
                "predicted_support": float(predicted_support[i]),
            }
            for i, label in enumerate(_LABELS)
        },
    }


def _read_hashed_rows(
    path: Path, *, schema: type[Record] | None = None, doc_ids: set[str] | None = None
) -> tuple[list, dict[str, str]]:
    digest = sha256()
    rows = []
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            digest.update(line)
            try:
                text = line.decode("utf-8-sig" if number == 1 else "utf-8").strip()
            except UnicodeDecodeError:
                raise ValueError(f"{path}:{number}: expected UTF-8") from None
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError(f"{path}:{number}: invalid JSON") from None
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected a JSON object")
            if doc_ids is not None and (
                not isinstance(row.get("doc_id"), str) or row["doc_id"] not in doc_ids
            ):
                continue
            try:
                rows.append(schema.model_validate(row) if schema else row)
            except ValidationError as exc:
                fields = ", ".join(
                    ".".join(map(str, error["loc"])) or "record"
                    for error in exc.errors(include_input=False)
                )
                raise ValueError(f"{path}:{number}: invalid fields: {fields}") from None
    return rows, {"path": str(path), "sha256": digest.hexdigest()}


@dataclass
class _RunData:
    inputs: list[ApplicabilityInput]
    groups: np.ndarray
    sources: np.ndarray
    label_ids: np.ndarray
    event_keys: list[tuple[str, str]]
    weights: np.ndarray
    profile_dependent: np.ndarray
    reason_masks: dict[str, np.ndarray]


def _create_run_data(
    rows: list[dict],
    notices: list[Notice],
    annotations: list[Annotation] | None,
    source: AudienceSource,
    *,
    allow_synthetic: bool,
) -> _RunData:
    usable_notices = {notice.doc_id: notice for notice in notices}
    inputs = build_inputs(rows, notices, annotations, source)
    events = [(item.doc_id, item.event_id) for item in inputs]
    profiles_by_event: dict[tuple[str, str], set[str]] = {}
    labels_by_event: dict[tuple[str, str], set[str]] = {}
    label_ids, reasons = [], []
    for line, (row, key, item) in enumerate(zip(rows, events, inputs, strict=True), 1):
        notice = usable_notices[item.doc_id]
        if notice.synthetic != row.get("synthetic", False) or (
            notice.synthetic and not allow_synthetic
        ):
            raise ValueError(f"pair line {line}: synthetic flag disagrees with the notice")
        if notice.domain_holdout:
            raise ValueError(f"pair line {line}: notice is marked as a domain holdout")
        profiles = profiles_by_event.setdefault(key, set())
        if item.profile_id in profiles:
            raise ValueError(f"pair line {line}: duplicate document/event/profile IDs")
        profiles.add(item.profile_id)
        label = row.get("label")
        if (
            row.get("label_origin") != _LABEL_ORIGIN
            or not isinstance(label, str)
            or label not in _LABEL_INDEX
        ):
            raise ValueError(f"pair line {line}: expected a three-way constraint_rule label")
        labels_by_event.setdefault(key, set()).add(label)
        label_ids.append(_LABEL_INDEX[label])
        reason = row.get("rule_reason")
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"pair line {line}: missing rule_reason")
        reasons.append(set(reason.split(";")))
    masks = _REASON_SLICES | {reason: {reason} for reason in _MISMATCH_REASONS}
    return _RunData(
        inputs=inputs,
        groups=np.array([row["group_id"] for row in rows]),
        sources=np.array([item.source_type for item in inputs]),
        label_ids=np.array(label_ids, dtype=np.intp),
        event_keys=events,
        weights=event_weights(events),
        profile_dependent=np.array([len(labels_by_event[key]) > 1 for key in events]),
        reason_masks={
            key: np.array([bool(tokens & targets) for tokens in reasons])
            for key, targets in masks.items()
        },
    )


@dataclass
class _Fold:
    seed: int
    fold: int
    web_groups: set[str]


def _plan_folds(
    data: _RunData, config: TrainingConfig
) -> tuple[list[dict], dict[int, np.ndarray], dict[str, list[_Fold]]]:
    fractions = sorted(config.learning_curve) if config.learning_curve is not None else [None]
    mix = ",".join(config.train_sources)
    keys = [f"mix={mix}" if fraction is None else f"fraction={fraction}" for fraction in fractions]
    experiments: dict[str, list[_Fold]] = {key: [] for key in keys}
    memberships = {}
    fold_rows = []
    groups = data.groups.tolist()
    source_groups = {
        source: set(data.groups[data.sources == source].tolist()) for source in _SOURCES
    }
    for seed in config.seeds:
        assignment = assign_folds(groups, config.folds, seed)
        memberships[seed] = np.array([assignment[group] for group in groups])
        fold_rows.extend(
            {"seed": seed, "group_id": group, "fold": assignment[group]}
            for group in sorted(assignment)
        )
        for fold in range(config.folds):
            train_groups = {group for group, assigned in assignment.items() if assigned != fold}
            web = train_groups & source_groups["web"] if "web" in config.train_sources else set()
            email = (
                train_groups & source_groups["email"] if "email" in config.train_sources else set()
            )
            subsets = (
                web_group_subsets(sorted(web), config.learning_curve, seed)
                if config.learning_curve is not None
                else {}
            )
            for key, fraction in zip(keys, fractions, strict=True):
                selected = web if fraction is None else subsets[fraction]
                if not (selected or email):
                    raise ValueError(
                        f"seed {seed}, fold {fold}, {key}: no training pairs after filtering"
                    )
                experiments[key].append(_Fold(seed, fold, selected))
    return fold_rows, memberships, experiments


def _fold_indices(
    data: _RunData, memberships: dict[int, np.ndarray], fold: _Fold, config: TrainingConfig
) -> tuple[np.ndarray, np.ndarray]:
    held_out = memberships[fold.seed] == fold.fold
    selected = (data.sources == "web") & np.isin(data.groups, sorted(fold.web_groups))
    if "email" in config.train_sources:
        selected |= data.sources == "email"
    return np.flatnonzero(~held_out & selected), np.flatnonzero(held_out)


def _fit(
    data: _RunData,
    indices: np.ndarray,
    config: TrainingConfig,
    params: dict,
    seed: int,
    lexicon: Lexicon,
) -> tuple[FeatureBuilder, LGBMClassifier, int]:
    items = [data.inputs[i] for i in indices]
    builder = FeatureBuilder(lexicon, tfidf=config.tfidf, source_feature=config.source_feature)
    matrix = builder.fit(items).transform(items)
    weights = data.weights[indices] if config.weighting == "event" else np.ones(len(indices))
    labels = data.label_ids[indices]
    majority = int(np.bincount(labels, weights=weights, minlength=len(_LABELS)).argmax())
    model = LGBMClassifier(
        objective="multiclass", num_class=len(_LABELS), random_state=seed, **params
    )
    try:
        model.fit(matrix, labels, sample_weight=weights)
    except LightGBMError as exc:
        raise ValueError(f"LightGBM fit failed for seed {seed}: {exc}") from None
    return builder, model, majority


def _predict(
    data: _RunData, indices: np.ndarray, builder: FeatureBuilder, model: LGBMClassifier
) -> np.ndarray:
    matrix = builder.transform([data.inputs[i] for i in indices])
    raw = model.booster_.predict(matrix)
    # LightGBM packs observed classes into the first columns. Drop unused columns
    # and return probabilities in the persisted label order even when a fold lacks a class.
    observed = raw[:, : len(model.classes_)]
    probabilities = np.zeros((len(indices), len(_LABELS)))
    probabilities[:, model.classes_] = observed / observed.sum(axis=1, keepdims=True)
    return probabilities


def _counts(data: _RunData, indices: np.ndarray) -> dict:
    keys = {data.event_keys[i] for i in indices}
    labels = np.bincount(data.label_ids[indices], minlength=len(_LABELS))
    return {
        "documents": len({doc_id for doc_id, _ in keys}),
        "events": len(keys),
        "pairs": len(indices),
        "labels": dict(zip(_LABELS, labels.tolist(), strict=True)),
        "source_pairs": {
            source: int(np.count_nonzero(data.sources[indices] == source)) for source in _SOURCES
        },
        "mismatch_reasons": {
            reason: int(np.count_nonzero(data.reason_masks[reason][indices]))
            for reason in _MISMATCH_REASONS
        },
    }


def _weighted_metrics(
    data: _RunData, indices: np.ndarray, pred: np.ndarray, baseline: np.ndarray
) -> tuple[dict, dict]:
    gold = data.label_ids[indices]
    count = len({data.event_keys[i] for i in indices})
    weights = {"event": data.weights[indices], "pair": np.ones(len(indices))}
    return tuple(
        {
            name: _label_metrics(gold, guesses, values) | {"n_events": count}
            for name, values in weights.items()
        }
        for guesses in (pred, baseline)
    )


def _evaluate(data: _RunData, indices: np.ndarray, pred: np.ndarray, baseline: np.ndarray) -> dict:
    def scores(mask: np.ndarray) -> tuple[dict, dict]:
        return _weighted_metrics(data, indices[mask], pred[mask], baseline[mask])

    overall = _weighted_metrics(data, indices, pred, baseline)
    sources = {source: scores(data.sources[indices] == source) for source in _SOURCES}
    profile_dependent = scores(data.profile_dependent[indices])
    reasons = {key: scores(data.reason_masks[key][indices]) for key in _REASON_SLICES}
    results = [
        {
            "overall": overall[i],
            "per_source": {key: values[i] for key, values in sources.items()},
            "profile_dependent": profile_dependent[i],
            "rule_reason": {key: values[i] for key, values in reasons.items()},
        }
        for i in range(2)
    ]
    return results[0] | {"majority_baseline": results[1]}


def _mean_std(records: list[dict]) -> dict:
    summary = {}
    for key, example in records[0].items():
        values = [record[key] for record in records]
        if isinstance(example, dict):
            summary[key] = _mean_std(values)
        else:
            summary[key] = {
                "mean": np.mean(values, axis=0).tolist(),
                "std": np.std(values, axis=0).tolist(),
            }
    return summary


@dataclass
class _ExperimentResult:
    scores: list[float]
    metrics: list[dict]
    fold_records: list[dict]
    names: list[dict]
    importances: list[dict]


def _gain(model: LGBMClassifier) -> list[float]:
    return model.booster_.feature_importance(importance_type="gain").tolist()


def _write_oof(
    stream: TextIO,
    data: _RunData,
    held_out: np.ndarray,
    probabilities: np.ndarray,
    predicted: np.ndarray,
    identity: dict,
) -> None:
    for index, row, guess in zip(held_out, probabilities.tolist(), predicted, strict=True):
        item = data.inputs[index]
        prediction = identity | {
            "doc_id": item.doc_id,
            "event_id": item.event_id,
            "profile_id": item.profile_id,
            "gold_label": _LABELS[data.label_ids[index]],
            "predicted_label": _LABELS[guess],
            "probabilities": dict(zip(_LABELS, row, strict=True)),
        }
        stream.write(json.dumps(prediction, ensure_ascii=False, allow_nan=False) + "\n")


def _cross_validate(
    data: _RunData,
    config: TrainingConfig,
    lexicon: Lexicon,
    params: dict,
    experiment: str,
    folds: list[_Fold],
    memberships: dict[int, np.ndarray],
    stream: TextIO | None = None,
) -> _ExperimentResult:
    result = _ExperimentResult([], [], [], [], [])
    all_indices = np.arange(len(data.inputs))
    for seed in config.seeds:
        seed_pred = np.empty_like(data.label_ids)
        seed_baseline = np.empty_like(data.label_ids)
        fold_metrics = []
        for fold in (split for split in folds if split.seed == seed):
            training, held_out = _fold_indices(data, memberships, fold, config)
            builder, model, majority = _fit(data, training, config, params, seed, lexicon)
            probabilities = _predict(data, held_out, builder, model)
            pred = probabilities.argmax(axis=1)
            seed_pred[held_out] = pred
            seed_baseline[held_out] = majority
            if stream is None:
                continue
            identity = {"seed": seed, "fold": fold.fold}
            _write_oof(
                stream, data, held_out, probabilities, pred, identity | {"experiment": experiment}
            )
            result.fold_records.append(
                identity
                | {
                    "train": _counts(data, training),
                    "held_out": _counts(data, held_out),
                    "selected_web_groups": sorted(fold.web_groups),
                    "majority_label": _LABELS[majority],
                }
            )
            result.names.append(identity | {"features": builder.feature_names})
            result.importances.append(identity | {"gain": _gain(model)})
            baseline = seed_baseline[held_out]
            fold_metrics.append(identity | _evaluate(data, held_out, pred, baseline))
        if stream is None:
            score = _label_metrics(data.label_ids, seed_pred, data.weights)
            result.scores.append(score["macro_f1"])
        else:
            oof = _evaluate(data, all_indices, seed_pred, seed_baseline)
            result.scores.append(oof["overall"]["event"]["macro_f1"])
            result.metrics.append({"seed": seed, "folds": fold_metrics, "oof": oof})
    return result


def _select_parameters(
    data: _RunData,
    config: TrainingConfig,
    lexicon: Lexicon,
    experiments: dict[str, list[_Fold]],
    memberships: dict[int, np.ndarray],
) -> tuple[dict, dict | None]:
    base = _DEFAULT_PARAMS | config.params
    if config.param_grid is None:
        return base, None
    experiment, folds = next(iter(experiments.items()))
    trials = []
    for overrides in config.param_grid:
        params = base | overrides
        result = _cross_validate(data, config, lexicon, params, experiment, folds, memberships)
        trials.append(
            {
                "params": params,
                "event_macro_f1_by_seed": dict(
                    zip(map(str, config.seeds), result.scores, strict=True)
                ),
                "mean_event_macro_f1": float(np.mean(result.scores)),
            }
        )
    selected = max(range(len(trials)), key=lambda i: trials[i]["mean_event_macro_f1"])
    return trials[selected]["params"], {
        "experiment": experiment,
        "selected_index": selected,
        "trials": trials,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def _git_provenance() -> dict:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], encoding="utf-8").strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], encoding="utf-8"
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Run applicability training from a SmartNotice Git checkout") from exc
    return {"git_commit": commit, "git_dirty": bool(dirty.strip())}


def _hash_set(rows: list[dict], field: str) -> list[str]:
    hashes = set()
    for number, row in enumerate(rows, 1):
        value = row.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError(f"pair line {number}: missing or invalid {field}")
        hashes.add(value)
    return sorted(hashes)


@contextmanager
def _run_directory(path: Path) -> Iterator[Path]:
    try:
        path.mkdir(parents=True)
    except FileExistsError:
        raise ValueError(f"Applicability run directory already exists: {path}") from None
    try:
        yield path
    except BaseException:
        for name in _RUN_FILES:
            (path / name).unlink(missing_ok=True)
        path.rmdir()
        raise


def run_training(
    config: TrainingConfig,
    *,
    pairs_path: Path,
    notices_path: Path,
    assignments_path: Path,
    annotations_path: Path | None = None,
    lexicon_path: Path = DEFAULT_LEXICON_PATH,
    output_dir: Path | None = None,
) -> Path:
    """Fit and score grouped folds, then return the newly created run directory.

    Input paths are UTF-8 JSONL except for the JSON lexicon. Provide annotations
    for human and predicted audience modes. The current checkout supplies Git
    and lockfile provenance. Raise ValueError for invalid joins, empty training
    folds, or an existing output directory.
    """
    started = datetime.now(UTC)
    config_values = config.model_dump(mode="json")
    config_digest = sha256(json.dumps(config_values, sort_keys=True).encode()).hexdigest()
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{config_digest[:8]}"
    destination = output_dir if output_dir is not None else _DEFAULT_OUTPUT_ROOT / run_id
    with _run_directory(destination) as output:
        record = _git_provenance()
        with Path("uv.lock").open("rb") as lock:
            record["uv_lock_sha256"] = file_digest(lock, "sha256").hexdigest()
        pairs, pairs_record = _read_hashed_rows(pairs_path)
        assignments, assignments_record = _read_hashed_rows(assignments_path)
        pool, policy = load_pool(pairs, assignments, allow_synthetic=config.allow_synthetic)
        if not pool:
            raise ValueError("No train/validation pairs remain after synthetic filtering")
        input_records = {"pairs": pairs_record, "assignments": assignments_record}
        doc_ids = {row["doc_id"] for row in pool}
        notices, input_records["notices"] = _read_hashed_rows(
            notices_path, schema=Notice, doc_ids=doc_ids
        )
        annotations = None
        if config.audience_source != "none":
            if annotations_path is None:
                raise ValueError(f"{config.audience_source} mode requires audience annotations")
            annotations, input_records["audience_annotations"] = _read_hashed_rows(
                annotations_path, schema=Annotation, doc_ids=doc_ids
            )
        lexicon, lexicon_hash = load_lexicon(lexicon_path)
        data = _create_run_data(
            pool,
            notices,
            annotations,
            config.audience_source,
            allow_synthetic=config.allow_synthetic,
        )
        record.update(
            run_id=run_id,
            created_at=started.isoformat(),
            config_sha256=config_digest,
            config=config_values,
            inputs=input_records,
            label_origin=_LABEL_ORIGIN,
            label_order=list(_LABELS),
            audience_policy=policy,
            audience_source=config.audience_source,
            train_sources=config.train_sources,
            learning_curve=config.learning_curve,
            seeds=config.seeds,
            folds=config.folds,
            weighting=config.weighting,
            lexicon_path=str(lexicon_path),
            lexicon_version=lexicon.version,
            lexicon_sha256=lexicon_hash,
            annotation_sha256=_hash_set(pool, "annotation_sha256"),
            profile_set_sha256=_hash_set(pool, "profile_set_sha256"),
            excluded_synthetic_pairs=len(pairs) - len(pool),
            synthetic_pairs=sum(row.get("synthetic", False) for row in pool),
            platform=platform.platform(),
            python_version=platform.python_version(),
            library_versions={
                name: version(name)
                for name in ("lightgbm", "scikit-learn", "numpy", "scipy", "pydantic")
            },
        )
        del pairs, pool, assignments, notices, annotations

        fold_rows, memberships, experiments = _plan_folds(data, config)
        params, selection = _select_parameters(data, config, lexicon, experiments, memberships)
        fixed_params = {"objective": "multiclass", "num_class": len(_LABELS)}
        record.update(
            default_params=_DEFAULT_PARAMS | fixed_params,
            params=params | fixed_params,
            parameter_selection=selection,
            selection_score_is_not_held_out=selection is not None,
            experiments={},
            pool_counts=_counts(data, np.arange(len(data.inputs))),
            final_fit=None,
        )
        write_jsonl(output / "folds.jsonl", fold_rows)
        metrics = {"label_origin": _LABEL_ORIGIN, "label_order": list(_LABELS), "experiments": {}}
        names = {"experiments": {}, "final": None}
        importances = {"experiments": {}, "final": None}
        with (output / "oof_predictions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for key, folds in experiments.items():
                result = _cross_validate(
                    data, config, lexicon, params, key, folds, memberships, stream
                )
                record["experiments"][key] = result.fold_records
                metrics["experiments"][key] = {
                    "seeds": result.metrics,
                    "across_seeds": _mean_std([seed["oof"] for seed in result.metrics]),
                }
                names["experiments"][key] = result.names
                importances["experiments"][key] = result.importances
        if config.fit_final:
            seed = config.seeds[0]
            indices = np.arange(len(data.inputs))
            builder, model, _ = _fit(data, indices, config, params, seed, lexicon)
            model.booster_.save_model(str(output / "model.txt"))
            _write_json(output / "tfidf.json", builder.tfidf_state())
            names["final"] = builder.feature_names
            importances["final"] = _gain(model)
            native_classes = [_LABELS[i] for i in model.classes_]
            record["final_fit"] = {
                "seed": seed,
                "counts": _counts(data, indices),
                "model_class_order": native_classes + [None] * (len(_LABELS) - len(native_classes)),
            }
        _write_json(output / "metrics.json", metrics)
        _write_json(output / "feature_names.json", names)
        _write_json(output / "importances.json", importances)
        _write_json(output / "record.json", record)
    return destination
