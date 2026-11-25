"""Verify grouped candidate filtering and offset provenance on synthetic data."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.candidate_data import CandidateCorpus
from smartnotice.labeling.candidate_generation import LABELS, generate_span_candidates
from smartnotice.labeling.candidate_metrics import evaluate_candidates
from smartnotice.preprocessing.text import segment_sentences


def test_candidate_generator_preserves_overlap_and_repeated_offsets(notices):
    text = (
        "Đối tượng: sinh viên K24. Không cần nộp hồ sơ trước ngày 25/11/2026. "
        "Qua https://example.invalid/form. Qua https://example.invalid/form."
    )
    notice = notices[0].model_copy(
        update={"text": text, "sentences": segment_sentences(text), "attachments": []}
    )
    candidates = generate_span_candidates(notice, dict.fromkeys(LABELS, 12))
    assert all(text[row.start : row.end] == row.text for row in candidates)
    pairs = {(row.text, row.proposed_label) for row in candidates}
    assert {
        ("sinh viên K24", "AUDIENCE"),
        ("nộp hồ sơ", "ACTION"),
        ("Không cần nộp hồ sơ", "ACTION"),
        ("25/11/2026", "TIME"),
    } <= pairs
    audience = next(row for row in candidates if row.text == "sinh viên K24")
    assert set(audience.rule_ids) >= {"field.value", "anchor.audience"}
    urls = [row for row in candidates if "channel.url" in row.rule_ids]
    assert len(urls) == 2 and urls[0].start < urls[1].start


def test_metrics_keep_generator_misses_in_full_recall_denominator():
    metrics = evaluate_candidates(
        [
            {
                "source": "email",
                "gold": {(0, 3, "ACTION"), (6, 9, "ACTION"), (12, 15, "TIME")},
                "emitted": {(0, 3, "ACTION"), (6, 9, "ACTION"), (12, 16, "TIME")},
                "kept": {(0, 3, "ACTION"), (12, 16, "TIME")},
            },
            {"source": "web", "gold": {(0, 5, "TIME")}, "emitted": set(), "kept": set()},
        ]
    )["overall"]
    assert metrics["candidate_recall"] == 0.5
    assert metrics["overlap_coverage"] == 0.75
    assert metrics["binary_positive"]["recall"] == 0.5
    assert metrics["exact_typed_span"]["recall"] == 0.25
    assert metrics["generated_gold_rejection_rate"] == 0.5


def test_generator_offers_a_boundary_at_the_learned_phrase_limit(notices):
    text = "Đăng ký dự thi vòng tuyển chọn của trường vào tháng sau."
    notice = notices[0].model_copy(
        update={"text": text, "sentences": segment_sentences(text), "attachments": []}
    )
    limits = dict.fromkeys(LABELS, 7)
    action = {
        row.text
        for row in generate_span_candidates(notice, limits)
        if row.proposed_label == "ACTION"
    }
    assert "Đăng ký dự thi vòng tuyển chọn" in action
    assert all(len(phrase.split()) <= 7 for phrase in action)


def test_frozen_groups_cannot_cross_splits(tmp_path):
    assignments = [
        {"doc_id": "a", "group_id": "same", "split": "train"},
        {"doc_id": "b", "group_id": "same", "split": "test"},
    ]
    write_jsonl(tmp_path / "assignments.jsonl", assignments)
    reviews = tmp_path / "reviews.jsonl"
    write_jsonl(reviews, [])
    with pytest.raises(ValueError, match="crosses frozen splits"):
        CandidateCorpus(tmp_path, reviews, synthetic=True)


def test_train_evaluate_and_predict_both_models(tmp_path):
    pytest.importorskip("sklearn")
    from smartnotice.labeling.candidate_cli import main

    fixture = tmp_path / "fixture"
    script = Path(__file__).resolve().parents[1] / "tools/create_candidate_demo.py"
    subprocess.run([sys.executable, str(script), str(fixture)], check=True)
    shared = ["--snapshot", str(fixture), "--reviews", str(fixture / "span-reviews.jsonl")]
    train_dir = tmp_path / "train"
    main(["train", "--synthetic", *shared, "--output", str(train_dir)])
    report = json.loads((train_dir / "report.json").read_text(encoding="utf-8"))
    assert report["group_cv"]["status"] == "completed"
    assert set(report["split_counts"]) == {"train", "validation"}
    models = ["--models", str(train_dir / "models.pkl")]
    domain = tmp_path / "domain"
    main(["evaluate", *models, *shared, "--split", "domain_test", "--output", str(domain)])
    output = tmp_path / "inference.jsonl"
    main(
        [
            "predict",
            *models,
            "--notices",
            str(fixture / "domain_test" / "notices.jsonl"),
            "--output",
            str(output),
        ]
    )
    names = {"logistic_combined", "forest_combined"}
    predictions = read_jsonl(output)
    assert {row["system"] for row in predictions} == names
    assert all("target" not in row and "text" not in row for row in predictions)
    keys = ("system", "start", "end", "proposed_label", "score", "prediction")
    expected = read_jsonl(domain / "predictions.jsonl")
    assert {tuple(row[key] for key in keys) for row in predictions} == {
        tuple(row[key] for key in keys) for row in expected if row["system"] in names
    }
