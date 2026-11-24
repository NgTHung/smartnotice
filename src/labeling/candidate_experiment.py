"""Train and apply both candidate filters on the same reviewed candidate batches."""

from dataclasses import dataclass
from math import ceil
from typing import cast

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from smartnotice.labeling.candidate_data import ReviewedNotice
from smartnotice.labeling.candidate_features import CandidateFeatures, candidate_feature_row
from smartnotice.labeling.candidate_generation import LABELS, generate_span_candidates
from smartnotice.labeling.candidate_metrics import evaluate_candidates, select_threshold
from smartnotice.labeling.candidates import build_candidate_targets
from smartnotice.schemas import CandidateTarget, Notice, SpanLabel

# Used when train contains no examples of a label. Structural time/URL patterns
# do not use these phrase limits.
_FALLBACK_UNITS = 12
_GRID = {
    "logistic": [{"C": value} for value in (1.0, 0.1, 10.0)],
    "forest": [
        {"max_depth": depth, "min_samples_leaf": leaf}
        for depth, leaf in ((15, 2), (15, 5), (None, 2), (None, 5))
    ],
}
_FEATURE_MODES = {
    "combined": {},
    "tfidf": {"context": False, "structured": False, "rules": False},
    "without_context": {"context": False},
    "without_rules": {"rules": False},
}


@dataclass
class _Batch:
    rows: list[dict]
    targets: list[CandidateTarget]
    documents: list[dict]
    sizes: list[int]


def _limits(documents):
    lengths = {label: [] for label in LABELS}
    for item in documents:
        unique = {(span.label, span.start, span.end, span.text) for span in item.spans}
        for label, _, _, text in unique:
            lengths[label].append(len(text.split()))
    return {
        cast(SpanLabel, label): max(1, sorted(values)[ceil(0.95 * len(values)) - 1])
        if values
        else _FALLBACK_UNITS
        for label, values in lengths.items()
    }


def _key(target):
    return target.start, target.end, target.proposed_label


def _batch(documents, limits):
    batch = _Batch([], [], [], [])
    for item in documents:
        candidates = generate_span_candidates(item.notice, limits)
        targets = build_candidate_targets(item.notice, candidates, item.annotation, item.review)
        batch.rows.extend(candidate_feature_row(item.notice, candidate) for candidate in candidates)
        batch.targets.extend(targets)
        batch.sizes.append(len(targets))
        batch.documents.append(
            {
                "gold": {(span.start, span.end, span.label) for span in item.spans},
                "emitted": {_key(row) for row in targets},
                "source": item.notice.source_type,
            }
        )
    return batch


def _score(batch, probabilities, threshold):
    start = 0
    documents = []
    for doc, size in zip(batch.documents, batch.sizes, strict=True):
        stop = start + size
        kept = {
            _key(row)
            for row, probability in zip(
                batch.targets[start:stop], probabilities[start:stop], strict=True
            )
            if probability >= threshold
        }
        documents.append({**doc, "kept": kept})
        start = stop
    return evaluate_candidates(documents)


def _model(family, params, seed):
    if family == "logistic":
        return LogisticRegression(max_iter=1000, random_state=seed, **params)
    return RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=1, **params)


def _fit(model, matrix, batch):
    if {row.target for row in batch.targets} != {0, 1}:
        raise ValueError("Training requires both positive and negative reviewed candidates")
    model.fit(matrix, [row.target for row in batch.targets])
    return model


def _probabilities(model, matrix):
    return model.predict_proba(matrix)[:, 1].tolist() if matrix is not None else []


def _cv(documents, seed):
    choices = {name: params[0] for name, params in _GRID.items()}
    groups = [item.group_id for item in documents]
    folds = min(3, len(set(groups)))
    if folds < 2:
        return choices, {"status": "insufficient_groups"}
    batches = []
    for train_ids, dev_ids in GroupKFold(n_splits=folds).split(documents, groups=groups):
        fold_train = [documents[index] for index in train_ids]
        limits = _limits(fold_train)
        a = _batch(fold_train, limits)
        b = _batch([documents[index] for index in dev_ids], limits)
        if {row.target for row in a.targets} != {0, 1} or not any(
            doc["gold"] for doc in b.documents
        ):
            return choices, {"status": "insufficient_class_or_gold_support"}
        encoder = CandidateFeatures().fit(a.rows)
        batches.append(
            (a, b, encoder.transform(a.rows), encoder.transform(b.rows) if b.rows else None)
        )
    results = {}
    for family, grid in _GRID.items():
        trials = []
        for params in grid:
            scores = []
            for train, validation, x_train, x_val in batches:
                model = _fit(_model(family, params, seed), x_train, train)
                metrics = _score(validation, _probabilities(model, x_val), 0.5)
                scores.append(metrics["overall"]["exact_typed_span"]["f1"])
            trials.append({"parameters": params, "fold_f1": scores, "mean_f1": sum(scores) / folds})
        choices[family] = max(trials, key=lambda trial: trial["mean_f1"])["parameters"]
        results[family] = trials
    return choices, {"status": "completed", "folds": folds, "trials": results}


def train_candidate_filters(
    train: list[ReviewedNotice], validation: list[ReviewedNotice], seed: int
) -> tuple[dict, dict, list[dict]]:
    """Fit rule and ML baselines, select thresholds on validation and return evidence."""
    if {doc.group_id for doc in train} & {doc.group_id for doc in validation}:
        raise ValueError("Training and validation groups overlap")
    limits = _limits(train)
    train_batch, val_batch = _batch(train, limits), _batch(validation, limits)
    if {row.target for row in train_batch.targets} != {0, 1}:
        raise ValueError("Training requires both positive and negative reviewed candidates")
    gold_count = sum(len(doc["gold"]) for doc in val_batch.documents)
    if not gold_count or not any(row.target == 1 for row in val_batch.targets):
        raise ValueError("Validation requires at least one generated gold candidate")
    parameters, cv = _cv(train, seed)
    artifact = {"max_units": limits, "encoders": {}, "models": {}}
    for mode, settings in _FEATURE_MODES.items():
        encoder = CandidateFeatures(**settings).fit(train_batch.rows)
        artifact["encoders"][mode] = encoder
        x_train = encoder.transform(train_batch.rows)
        x_val = encoder.transform(val_batch.rows)
        families = tuple(_GRID) if mode == "combined" else ("logistic",)
        for family in families:
            model = _fit(_model(family, parameters[family], seed), x_train, train_batch)
            threshold = select_threshold(
                _probabilities(model, x_val), val_batch.targets, gold_count
            )
            artifact["models"][f"{family}_{mode}"] = {
                "encoder": mode,
                "estimator": model,
                "threshold": threshold,
            }
    metrics, predictions = _evaluate(artifact, val_batch)
    return (
        artifact,
        {
            "group_cv": cv,
            "max_units": limits,
            "length_quantile": 0.95,
            "fallback_units": _FALLBACK_UNITS,
            "training_targets": {
                "positive": sum(row.target == 1 for row in train_batch.targets),
                "negative": sum(row.target == 0 for row in train_batch.targets),
            },
            "models": {
                name: {"parameters": spec["estimator"].get_params(), "threshold": spec["threshold"]}
                for name, spec in artifact["models"].items()
            },
            "validation": metrics,
        },
        predictions,
    )


def _evaluate(artifact, batch):
    scores = {"rules": ([1.0] * len(batch.targets), 1.0)}
    matrices = {}
    for mode, encoder in artifact["encoders"].items():
        matrices[mode] = encoder.transform(batch.rows) if batch.rows else None
    for name, spec in artifact["models"].items():
        probabilities = _probabilities(spec["estimator"], matrices[spec["encoder"]])
        scores[name] = probabilities, spec["threshold"]

    metrics = {}
    predictions = []
    for name, (probabilities, threshold) in scores.items():
        metrics[name] = {"selected_threshold": _score(batch, probabilities, threshold)}
        if name != "rules":
            metrics[name]["threshold_0.5"] = _score(batch, probabilities, 0.5)
        for row, probability in zip(batch.targets, probabilities, strict=True):
            predictions.append(
                {
                    **row.model_dump(mode="json"),
                    "system": name,
                    "score": probability,
                    "threshold": threshold,
                    "prediction": int(probability >= threshold),
                }
            )
    return metrics, predictions


def evaluate_candidate_filters(
    artifact: dict, documents: list[ReviewedNotice]
) -> tuple[dict, list[dict]]:
    """Evaluate frozen models and thresholds against the supplied reviewed documents."""
    return _evaluate(artifact, _batch(documents, artifact["max_units"]))


def predict_candidate_filters(artifact: dict, notices: list[Notice]) -> list[dict]:
    """Return offset-only candidate predictions for both fitted algorithms without gold."""
    predictions = []
    encoder = artifact["encoders"]["combined"]
    for notice in notices:
        candidates = generate_span_candidates(notice, artifact["max_units"])
        rows = [candidate_feature_row(notice, candidate) for candidate in candidates]
        matrix = encoder.transform(rows) if rows else None
        for name in ("logistic_combined", "forest_combined"):
            spec = artifact["models"][name]
            scores = _probabilities(spec["estimator"], matrix)
            for candidate, score in zip(candidates, scores, strict=True):
                predictions.append(
                    {
                        **candidate.model_dump(mode="json", exclude={"text"}),
                        "system": name,
                        "score": score,
                        "threshold": spec["threshold"],
                        "prediction": int(score >= spec["threshold"]),
                    }
                )
    return predictions
