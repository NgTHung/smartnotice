import json
from collections import defaultdict
from hashlib import sha256

import pytest
from applicability_fixture import make_corpus
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.modeling.applicability_training import (
    TrainingConfig,
    assign_folds,
    compute_metrics,
    event_weights,
    load_pool,
    run_training,
    web_group_subsets,
)
from smartnotice.modeling.lexicon import DEFAULT_LEXICON_PATH


@pytest.fixture
def corpus():
    return make_corpus()


def _input_paths(tmp_path, corpus):
    notices, annotations, _, pairs, assignments = corpus
    paths = {}
    for name, rows in {
        "pairs": pairs,
        "notices": [row.model_dump(mode="json") for row in notices],
        "assignments": assignments,
        "annotations": [row.model_dump(mode="json") for row in annotations],
    }.items():
        path = tmp_path / f"{name}.jsonl"
        write_jsonl(path, rows)
        paths[f"{name}_path"] = path
    return paths


@pytest.fixture
def paths(tmp_path, corpus):
    return _input_paths(tmp_path, corpus)


def _config(**overrides):
    return TrainingConfig(
        **(
            {
                "audience_source": "human",
                "folds": 3,
                "seeds": [42],
                "allow_synthetic": True,
                "params": {"n_estimators": 3, "min_child_samples": 1},
            }
            | overrides
        )
    )


def _run(config, paths, output_dir):
    return run_training(config, **paths, lexicon_path=DEFAULT_LEXICON_PATH, output_dir=output_dir)


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("split", ["test", "domain_test", "excluded"])
def test_test_split_pair_stops(corpus, split):
    *_, pairs, assignments = corpus
    assignments[0] = assignments[0] | {"split": split}
    with pytest.raises(ValueError, match=f"pair line 1.*{split}"):
        load_pool(pairs, assignments, allow_synthetic=True)


def test_unassigned_pair_stops(corpus):
    *_, pairs, assignments = corpus
    with pytest.raises(ValueError, match="pair line 1.*assignment"):
        load_pool(pairs, assignments[1:], allow_synthetic=True)


def test_mixed_policy_stops(corpus):
    *_, pairs, assignments = corpus
    pairs[1] = pairs[1] | {"audience_policy": "assume_all_students_without_audience"}
    with pytest.raises(ValueError, match="mixed.*audience_policy"):
        load_pool(pairs, assignments, allow_synthetic=True)


def test_synthetic_excluded_by_default(corpus):
    *_, pairs, assignments = corpus
    pairs[0] = pairs[0] | {"synthetic": False}
    pool, policy = load_pool(pairs, assignments, allow_synthetic=False)
    assert pool == [pairs[0] | {"split": "train", "group_id": "g0"}]
    assert policy is None


def test_groups_stay_in_one_fold(corpus):
    *_, pairs, assignments = corpus
    pool, _ = load_pool(pairs, assignments, allow_synthetic=True)
    groups = [row["group_id"] for row in pool]
    folds = assign_folds(groups, 3, 42)
    assert set(folds) == set(groups)
    assert set(folds.values()) == {0, 1, 2}
    for group in set(groups):
        assert len({folds[row["group_id"]] for row in pool if row["group_id"] == group}) == 1


def test_folds_independent_of_train_sources(tmp_path, paths):
    mix = _run(_config(), paths, tmp_path / "mix")
    curve = _run(
        _config(train_sources=["web"], learning_curve=[0.25, 1.0]), paths, tmp_path / "curve"
    )
    assert (mix / "folds.jsonl").read_bytes() == (curve / "folds.jsonl").read_bytes()
    predictions = read_jsonl(curve / "oof_predictions.jsonl")
    assert len(predictions) == 2 * len(read_jsonl(mix / "oof_predictions.jsonl"))
    experiments = _json(curve / "record.json")["experiments"]
    for small, full in zip(experiments["fraction=0.25"], experiments["fraction=1.0"], strict=True):
        assert set(small["selected_web_groups"]) <= set(full["selected_web_groups"])


def test_learning_curve_subsets_nested():
    groups = [f"g{i}" for i in range(8)]
    selected = web_group_subsets(groups + [groups[0]], [1.0, 0.25, 0.5], 42)
    assert selected[0.25] < selected[0.5] < selected[1.0] == set(groups)
    assert len(selected[0.25]) == 2
    assert selected == web_group_subsets(list(reversed(groups)), [0.25, 0.5, 1.0], 42)


def test_empty_training_fold_stops(tmp_path):
    corpus = make_corpus(n_docs=6, web_every=10)
    paths = _input_paths(tmp_path, corpus)
    output = tmp_path / "empty"
    with pytest.raises(ValueError, match=r"seed 42.*fold \d.*no training pairs"):
        _run(_config(train_sources=["web"], learning_curve=[0.25]), paths, output)
    assert not output.exists()


def test_metrics_with_absent_class():
    metrics = compute_metrics(["APPLIES", "NOT_APPLIES"], ["APPLIES", "APPLIES"], [1.0, 1.0])
    assert metrics["per_class"]["UNCLEAR"] == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "support": 0.0,
        "predicted_support": 0.0,
    }
    assert metrics["confusion_matrix"] == [[1, 0, 0], [1, 0, 0], [0, 0, 0]]
    assert metrics["macro_f1"] == pytest.approx(2 / 9)
    assert metrics["applies_recall"] == 1.0


def test_event_weighting_sums_to_one_per_event():
    keys = [("a", "event"), ("a", "event"), ("b", "event")]
    totals = defaultdict(float)
    for key, weight in zip(keys, event_weights(keys), strict=True):
        totals[key] += weight
    assert dict(totals) == {("a", "event"): 1.0, ("b", "event"): 1.0}


def test_same_seed_same_predictions(tmp_path, paths):
    first = _run(_config(), paths, tmp_path / "first")
    second = _run(_config(), paths, tmp_path / "second")
    assert (first / "oof_predictions.jsonl").read_bytes() == (
        second / "oof_predictions.jsonl"
    ).read_bytes()


def test_existing_run_dir_refused(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    input_paths = {
        f"{name}_path": tmp_path / "missing"
        for name in ("pairs", "notices", "assignments", "annotations")
    }
    with pytest.raises(ValueError, match="already exists"):
        _run(_config(), input_paths, output)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_run_writes_complete_record(tmp_path, paths):
    out = _run(
        _config(fit_final=True, param_grid=[{"num_leaves": 5}, {"num_leaves": 7}], seeds=[42, 43]),
        paths,
        tmp_path / "run",
    )
    assert {path.name for path in out.iterdir()} == {
        "record.json",
        "folds.jsonl",
        "oof_predictions.jsonl",
        "metrics.json",
        "feature_names.json",
        "importances.json",
        "model.txt",
        "tfidf.json",
    }
    record = _json(out / "record.json")
    assert {"uv_lock_sha256", "lexicon_sha256", "audience_policy", "train_sources"} <= record.keys()
    assert (
        record["inputs"]["pairs"]["sha256"] == sha256(paths["pairs_path"].read_bytes()).hexdigest()
    )
    assert record["selection_score_is_not_held_out"] is True
    assert record["annotation_sha256"]
    assert record["profile_set_sha256"]
    assert record["final_fit"]["counts"]["pairs"] == 36
    metrics = _json(out / "metrics.json")
    assert metrics["label_origin"] == "constraint_rule"
    experiment = metrics["experiments"]["mix=email,web"]
    assert len(experiment["seeds"]) == 2
    oof = experiment["seeds"][0]["oof"]
    assert set(oof["per_source"]) == {"email", "web"}
    assert oof["profile_dependent"]["pair"]["n_pairs"] == 36
    assert oof["overall"]["event"]["weight"] == pytest.approx(12)
    assert oof["majority_baseline"]["overall"]["pair"]["n_pairs"] == 36
    assert "std" in experiment["across_seeds"]["overall"]["event"]["macro_f1"]
    predictions = read_jsonl(out / "oof_predictions.jsonl")
    assert len(predictions) == 72
    assert all(sum(row["probabilities"].values()) == pytest.approx(1.0) for row in predictions)


def test_training_fold_with_missing_labels_keeps_fixed_probability_columns(tmp_path, corpus):
    *_, pairs, _ = corpus
    for pair in pairs:
        if pair["label"] == "UNCLEAR":
            pair["label"] = "APPLIES"
    paths = _input_paths(tmp_path, corpus)
    out = _run(_config(), paths, tmp_path / "absent")
    for row in read_jsonl(out / "oof_predictions.jsonl"):
        assert set(row["probabilities"]) == {"APPLIES", "NOT_APPLIES", "UNCLEAR"}
        assert row["probabilities"]["UNCLEAR"] == 0.0
