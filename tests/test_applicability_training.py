import json
from collections import defaultdict
from hashlib import sha256

import pytest
from applicability_fixture import make_corpus
from scipy import sparse
from sklearn.preprocessing import MaxAbsScaler
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.modeling import applicability_training
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


@pytest.mark.parametrize("absent", ["NOT_APPLIES", "UNCLEAR"])
def test_training_fold_with_missing_labels_keeps_fixed_probability_columns(
    tmp_path, corpus, absent
):
    *_, pairs, _ = corpus
    pairs[:] = [pair for pair in pairs if pair["label"] != absent]
    paths = _input_paths(tmp_path, corpus)
    out = _run(_config(), paths, tmp_path / "absent")
    for row in read_jsonl(out / "oof_predictions.jsonl"):
        assert set(row["probabilities"]) == {"APPLIES", "NOT_APPLIES", "UNCLEAR"}
        assert row["probabilities"][absent] == 0.0


def test_cli_train_applicability(tmp_path, paths, capsys):
    from smartnotice.cli import main

    output = tmp_path / "cli-run"
    params_file, grid_file = tmp_path / "params.json", tmp_path / "grid.json"
    params_file.write_text('{"n_estimators": 3, "min_child_samples": 1}', encoding="utf-8")
    grid_file.write_text('[{"num_leaves": 5}]', encoding="utf-8")
    main(
        [
            "train-applicability",
            "--pairs",
            str(paths["pairs_path"]),
            "--notices",
            str(paths["notices_path"]),
            "--assignments",
            str(paths["assignments_path"]),
            "--audience-source",
            "human",
            "--audience-annotations",
            str(paths["annotations_path"]),
            "--lexicon",
            str(DEFAULT_LEXICON_PATH),
            "--train-sources",
            "web",
            "--learning-curve",
            "0.5",
            "1.0",
            "--allow-synthetic",
            "--folds",
            "3",
            "--seeds",
            "42",
            "--no-tfidf",
            "--no-source-feature",
            "--weighting",
            "pair",
            "--params",
            str(params_file),
            "--param-grid",
            str(grid_file),
            "--fit-final",
            "--output-dir",
            str(output),
        ]
    )
    assert capsys.readouterr().out.strip() == str(output)
    record = _json(output / "record.json")
    assert record["config"]["tfidf"] is False
    assert record["config"]["source_feature"] is False
    assert record["config"]["weighting"] == "pair"
    assert record["train_sources"] == ["web"]
    assert record["learning_curve"] == [0.5, 1.0]
    assert record["params"]["n_estimators"] == 3
    assert record["params"]["num_leaves"] == 5
    assert record["inputs"]["params"]["sha256"] == sha256(params_file.read_bytes()).hexdigest()
    assert record["inputs"]["param_grid"]["sha256"] == sha256(grid_file.read_bytes()).hexdigest()
    assert _json(output / "tfidf.json") is None


def test_final_fit_respects_train_sources(tmp_path, paths):
    out = _run(_config(fit_final=True, train_sources=["web"]), paths, tmp_path / "run")
    counts = _json(out / "record.json")["final_fit"]["counts"]
    assert counts["source_pairs"]["email"] == 0
    assert counts["source_pairs"]["web"] > 0


def test_logreg_run_writes_complete_record(tmp_path, paths):
    logreg = _run(
        _config(model="logreg", params={}, param_grid=[{"C": 0.5}, {"C": 2.0}]),
        paths,
        tmp_path / "logreg",
    )
    lightgbm = _run(_config(), paths, tmp_path / "lightgbm")
    assert (logreg / "folds.jsonl").read_bytes() == (lightgbm / "folds.jsonl").read_bytes()
    features = _json(logreg / "feature_names.json")
    assert features == _json(lightgbm / "feature_names.json")
    record = _json(logreg / "record.json")
    assert record["model"] == "logreg"
    assert record["default_params"] == {"C": 1.0, "max_iter": 1000, "solver": "lbfgs"}
    selection = record["parameter_selection"]
    assert record["selection_score_is_not_held_out"] is True
    assert [trial["params"]["C"] for trial in selection["trials"]] == [0.5, 2.0]
    assert record["params"] == selection["trials"][selection["selected_index"]]["params"]
    metrics = _json(logreg / "metrics.json")
    assert metrics["model"] == "logreg"
    experiment = "mix=email,web"
    assert (
        metrics["experiments"][experiment]["seeds"][0]["oof"]["overall"]["event"]["n_pairs"] == 36
    )
    predictions = read_jsonl(logreg / "oof_predictions.jsonl")
    assert len(predictions) == 36
    label_order = ["APPLIES", "NOT_APPLIES", "UNCLEAR"]
    for row in predictions:
        assert list(row["probabilities"]) == label_order
        assert sum(row["probabilities"].values()) == pytest.approx(1.0)
    importances = _json(logreg / "importances.json")["experiments"][experiment]
    for fold, names in zip(importances, features["experiments"][experiment], strict=True):
        assert list(fold["coefficients"]) == label_order
        assert all(
            len(values) == len(names["features"]) for values in fold["coefficients"].values()
        )


def test_logreg_same_seed_same_predictions(tmp_path, paths):
    config = _config(model="logreg", params={})
    first = _run(config, paths, tmp_path / "first")
    second = _run(config, paths, tmp_path / "second")
    assert (first / "oof_predictions.jsonl").read_bytes() == (
        second / "oof_predictions.jsonl"
    ).read_bytes()


def test_logreg_scaler_fits_training_fold_only(tmp_path, corpus, monkeypatch):
    *_, pairs, assignments = corpus
    distant_doc = assignments[0]["doc_id"]
    for pair in pairs:
        if pair["doc_id"] == distant_doc and pair["profile_id"] == "older":
            pair["profile"]["cohort"] = 2000
    paths = _input_paths(tmp_path, corpus)
    fitted_maxima = []
    original_fit = MaxAbsScaler.fit

    def record_fit(scaler, matrix, *args, **kwargs):
        assert sparse.issparse(matrix)
        fitted = original_fit(scaler, matrix, *args, **kwargs)
        fitted_maxima.append(fitted.max_abs_.tolist())
        return fitted

    monkeypatch.setattr(MaxAbsScaler, "fit", record_fit)
    out = _run(_config(model="logreg", params={}), paths, tmp_path / "logreg")
    distant_group = assignments[0]["group_id"]
    held_out = next(
        row["fold"] for row in read_jsonl(out / "folds.jsonl") if row["group_id"] == distant_group
    )
    scaled_features = applicability_training.SCALED_FEATURES
    assert len(fitted_maxima) == 3
    assert all(len(maxima) == len(scaled_features) for maxima in fitted_maxima)
    distance = scaled_features.index("cohort_distance")
    assert [maxima[distance] for maxima in fitted_maxima] == [
        1.0 if fold == held_out else 24.0 for fold in range(3)
    ]


@pytest.mark.parametrize(
    ("model", "option", "invalid"),
    [
        ("logreg", "params", {"num_leaves": 5}),
        ("logreg", "param_grid", {"learning_rate": 0.1}),
        ("logreg", "params", {"random_state": 20}),
        ("lightgbm", "params", {"C": 0.5}),
        ("lightgbm", "param_grid", {"class_weight": "balanced"}),
    ],
)
def test_logreg_rejects_lightgbm_params(model, option, invalid):
    options = {"model": model, "params": {}, option: invalid if option == "params" else [invalid]}
    with pytest.raises(ValueError, match=rf"parameters.*\b{next(iter(invalid))}\b"):
        _config(**options)


def test_logreg_fit_final_writes_json_model(tmp_path, paths, capsys):
    from smartnotice.cli import main

    out = tmp_path / "logreg"
    main(
        [
            "train-applicability",
            "--pairs",
            str(paths["pairs_path"]),
            "--notices",
            str(paths["notices_path"]),
            "--assignments",
            str(paths["assignments_path"]),
            "--audience-source",
            "human",
            "--audience-annotations",
            str(paths["annotations_path"]),
            "--model",
            "logreg",
            "--allow-synthetic",
            "--folds",
            "3",
            "--seeds",
            "42",
            "--fit-final",
            "--output-dir",
            str(out),
        ]
    )
    assert capsys.readouterr().out.strip() == str(out)
    assert {path.name for path in out.iterdir()} == {
        "record.json",
        "folds.jsonl",
        "oof_predictions.jsonl",
        "metrics.json",
        "feature_names.json",
        "importances.json",
        "model.json",
        "tfidf.json",
    }
    model = _json(out / "model.json")
    assert model["classes"] == ["APPLIES", "NOT_APPLIES", "UNCLEAR"]
    assert model["feature_names"] == _json(out / "feature_names.json")["final"]
    assert model["scaler"]["max_abs"]["cohort_distance"] == 1.0
    assert model["scaler"]["max_abs"]["audience_chars"] == len("sinh viên K24")
    assert set(model["scaler"]["max_abs"]) == set(applicability_training.SCALED_FEATURES)
    assert len(model["coef"]) == len(model["intercept"]) == 3
    assert all(len(row) == len(model["feature_names"]) for row in model["coef"])
    assert _json(out / "record.json")["final_fit"]["model_class_order"] == model["classes"]
    assert _json(out / "importances.json")["final"] == dict(
        zip(model["classes"], model["coef"], strict=True)
    )


@pytest.mark.parametrize("absent", [{"NOT_APPLIES"}, {"UNCLEAR"}, {"APPLIES", "UNCLEAR"}])
def test_logreg_missing_class_keeps_probability_columns(tmp_path, corpus, absent):
    *_, pairs, _ = corpus
    pairs[:] = [pair for pair in pairs if pair["label"] not in absent]
    paths = _input_paths(tmp_path, corpus)
    out = _run(_config(model="logreg", params={}, fit_final=True), paths, tmp_path / "absent")
    labels = ["APPLIES", "NOT_APPLIES", "UNCLEAR"]
    for row in read_jsonl(out / "oof_predictions.jsonl"):
        probabilities = row["probabilities"]
        assert list(probabilities) == labels
        assert all(probabilities[label] == 0.0 for label in absent)
        assert sum(probabilities.values()) == pytest.approx(1.0)
    model = _json(out / "model.json")
    assert model["classes"] == [label for label in labels if label not in absent]
    assert len(model["coef"]) == len(model["intercept"]) == len(model["classes"])
