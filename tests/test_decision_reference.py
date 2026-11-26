import asyncio
import json

import httpx
import pytest
from applicability_fixture import make_corpus
from smartnotice.io import read_jsonl
from smartnotice.modeling.applicability_features import build_inputs
from smartnotice.modeling.decision_reference import (
    LABELS,
    PROVIDERS,
    agreement,
    build_request,
    parse_answers,
    run_requests,
    score_pilot,
    select_pilot,
)
from smartnotice.modeling.lexicon import DEFAULT_LEXICON_PATH, load_lexicon

FORBIDDEN = ("rule_reason", "label_origin", "audience_policy", "annotation_sha256", "cohorts")


def _corpus():
    notices, annotations, profiles, pairs, _ = make_corpus(n_docs=12)
    sources = {notice.doc_id: notice.source_type for notice in notices}
    return notices, annotations, pairs, sources


def test_pilot_sample_meets_source_quotas_and_limits_profiles_per_event():
    _, annotations, pairs, sources = _corpus()
    sample = select_pilot(
        pairs, annotations, sources, quotas={"web": 3, "email": 2}, profiles_per_event=2, seed=7
    )
    events = {(row["doc_id"], row["event_id"]) for row in sample}
    assert sorted(sources[doc] for doc, _ in events) == ["email"] * 2 + ["web"] * 3
    per_event = {key: sum((r["doc_id"], r["event_id"]) == key for r in sample) for key in events}
    assert set(per_event.values()) == {2}
    assert {row["label"] for row in sample} >= {"APPLIES", "NOT_APPLIES"}
    again = select_pilot(
        pairs, annotations, sources, quotas={"web": 3, "email": 2}, profiles_per_event=2, seed=7
    )
    assert again == sample


def test_pilot_sample_rejects_a_quota_the_pool_cannot_fill():
    _, annotations, pairs, sources = _corpus()
    with pytest.raises(ValueError, match="web"):
        select_pilot(pairs, annotations, sources, quotas={"web": 99}, profiles_per_event=2, seed=7)


def test_request_sends_allowlisted_inputs_with_one_question_per_profile():
    notices, annotations, pairs, _ = _corpus()
    event_pairs = [p for p in pairs if p["doc_id"] == pairs[0]["doc_id"]]
    lexicon, _ = load_lexicon(DEFAULT_LEXICON_PATH)
    for mode in ("human", "none"):
        inputs = build_inputs(event_pairs, notices, annotations, mode)
        payload, questions = build_request("jev-1.14.0", inputs, lexicon)
        text = json.dumps(payload, ensure_ascii=False)
        assert not any(key in text for key in FORBIDDEN)
        assert payload["model"] == "jev-1.14.0"
        assert sorted(questions.values()) == sorted(p["profile_id"] for p in event_pairs)
        assert all(set(q["criteria"]) == set(LABELS) for q in payload["questions"].values())
        assert ("audience_spans" in payload["state"]) is (mode == "human")
    other = [p for p in pairs if p["doc_id"] != pairs[0]["doc_id"]][:1]
    with pytest.raises(ValueError, match="one event"):
        build_request(
            "jev-1.14.0", build_inputs(event_pairs + other, notices, None, "none"), lexicon
        )


def _answer(choice, probabilities):
    return {"type": "choice", "choice": choice, "confidence": 0.5, "probabilities": probabilities}


def test_answers_with_unknown_labels_or_invalid_probabilities_fail():
    good = {"APPLIES": 0.7, "NOT_APPLIES": 0.2, "UNCLEAR": 0.1}
    parsed = parse_answers({"answers": {"q1": _answer("APPLIES", good)}}, {"q1": "p1"})
    assert parsed == {"p1": {"choice": "APPLIES", "probabilities": good, "confidence": 0.5}}
    bad = [
        {"answers": {}},
        {"answers": {"q1": _answer("MAYBE", good)}},
        {"answers": {"q1": _answer("APPLIES", {"APPLIES": 0.7, "UNCLEAR": 0.1})}},
        {"answers": {"q1": _answer("APPLIES", {**good, "APPLIES": 1.5})}},
    ]
    for body in bad:
        with pytest.raises(ValueError):
            parse_answers(body, {"q1": "p1"})


def test_runner_retries_rate_limits_records_no_text_and_resumes(tmp_path):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "slow"})
        probabilities = {"APPLIES": 0.1, "NOT_APPLIES": 0.8, "UNCLEAR": 0.1}
        answers = {"q1": _answer("NOT_APPLIES", probabilities)}
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": answers, "usage": {}})

    job = {
        "request_id": "none:d1:e1:0",
        "payload": {"model": "jev-1.14.0", "state": {"event_text": "BÍ MẬT"}, "questions": {}},
        "questions": {"q1": "p1"},
        "meta": {"mode": "none", "doc_id": "d1", "event_id": "e1", "repeat": 0},
    }
    output = tmp_path / "responses.jsonl"

    async def no_sleep(_):
        return None

    def run():
        asyncio.run(
            run_requests(
                [job],
                PROVIDERS["jev"],
                "key",
                output,
                concurrency=2,
                rate=100,
                transport=httpx.MockTransport(handler),
                sleep=no_sleep,
            )
        )

    run()
    rows = read_jsonl(output)
    assert len(calls) == 2
    assert rows[0]["status"] == 200 and rows[0]["attempts"] == 2
    assert rows[0]["answers"]["p1"]["choice"] == "NOT_APPLIES"
    assert "BÍ MẬT" not in output.read_text(encoding="utf-8")
    run()
    assert len(calls) == 2


def test_pilot_scores_report_denominators_calibration_and_consistency():
    sample = [
        {"doc_id": "d1", "event_id": "e1", "profile_id": "p1", "label": "APPLIES"},
        {"doc_id": "d1", "event_id": "e1", "profile_id": "p2", "label": "UNCLEAR"},
        {"doc_id": "d2", "event_id": "e1", "profile_id": "p1", "label": "NOT_APPLIES"},
    ]
    for row in sample:
        row |= {"source_type": "web", "group_id": row["doc_id"]}

    def answer(label):
        return {
            "choice": label,
            "confidence": 1.0,
            "probabilities": {k: float(k == label) for k in LABELS},
        }

    rows = [
        {
            "status": 200,
            "mode": "human",
            "doc_id": "d1",
            "event_id": "e1",
            "repeat": repeat,
            "latency_ms": 100.0,
            "answers": {"p1": answer("APPLIES"), "p2": answer("UNCLEAR")},
        }
        for repeat in (0, 1)
    ] + [
        {
            "status": 200,
            "mode": "human",
            "doc_id": "d2",
            "event_id": "e1",
            "repeat": 0,
            "latency_ms": 300.0,
            "answers": {"p1": answer("NOT_APPLIES")},
        },
        {
            "status": 503,
            "mode": "human",
            "doc_id": "d3",
            "event_id": "e1",
            "repeat": 0,
            "latency_ms": 50.0,
            "answers": None,
        },
    ]
    scores = score_pilot(rows, sample, seed=1, n_boot=50)
    human = scores["modes"]["human"]
    assert scores["requests"] == {"total": 4, "ok": 3, "failed_by_status": {"503": 1}}
    assert human["all"]["metrics"]["n_pairs"] == 3
    assert human["all"]["metrics"]["macro_f1"] == 1.0
    assert human["all"]["brier"] == 0.0
    assert sum(b["count"] for b in human["all"]["ece_bins"]) == 3
    assert human["all"]["missing_pairs"] == 0
    assert scores["consistency"]["human"] == {
        "pairs": 2,
        "same_choice": 1.0,
        "max_abs_prob_diff": 0.0,
    }
    assert agreement(rows, rows, "human") == {"pairs": 3, "same_choice": 1.0}
