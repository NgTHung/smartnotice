import copy
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from smartnotice.cli import main
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.llm import parse_proposal, require_provider_approval, text_sha256
from smartnotice.labeling.providers import configured_model, generate_draft, load_local_env
from smartnotice.labeling.studio import export_prediction_task, import_reviewed_tasks
from smartnotice.labeling.workflow import suggest_tasks
from smartnotice.preprocessing.text import segment_sentences


def draft_for(annotation, notice):
    return {
        "spans": [
            {
                "span_id": span.span_id,
                "label": span.label,
                "sentence_id": next(
                    s.sentence_id
                    for s in notice.sentences
                    if s.start <= span.start and span.end <= s.end
                ),
                "text": span.text,
            }
            for span in annotation.spans
        ],
        "events": [
            {
                "event_id": e.event_id,
                "action_span_id": e.action_span_id,
                "arguments": [{"span_id": a.span_id, "role": a.role} for a in e.arguments],
            }
            for e in annotation.events
        ],
    }


@pytest.fixture
def example(notices, annotations):
    annotation = annotations[0]
    notice = next(n for n in notices if n.doc_id == annotation.doc_id)
    draft = draft_for(annotation, notice)
    proposal = parse_proposal(notice, json.dumps(draft))
    task = export_prediction_task(notice, proposal, provider="gemini", model="test-model")
    return notice, draft, task


def test_proposal_resolves_shared_arguments_and_preserves_evidence(notices, annotations):
    for annotation in annotations:
        notice = next(n for n in notices if n.doc_id == annotation.doc_id)
        parsed = parse_proposal(notice, json.dumps(draft_for(annotation, notice)))
        assert parsed.spans == annotation.spans
        assert [e.evidence_sentence_ids for e in parsed.events] == [
            e.evidence_sentence_ids for e in annotation.events
        ]
        assert parsed.annotator_id == "model_prediction"
        assert all(a.normalized_date is None for e in parsed.events for a in e.arguments)
        assert parsed.audience_constraints == []


@pytest.mark.parametrize(
    "defect", ["quote", "label", "role", "link", "duplicate", "orphan", "duplicate_action"]
)
def test_invalid_proposals_fail(example, defect):
    notice, draft, _ = example
    if defect == "quote":
        draft["spans"][0]["text"] = "unsupported synthetic quote"
    elif defect == "label":
        draft["spans"][0]["label"] = "UNKNOWN"
    elif defect == "role":
        draft["events"][0]["arguments"][1]["role"] = None
    elif defect == "link":
        draft["events"][0]["arguments"][0]["span_id"] = "missing"
    elif defect == "duplicate":
        draft["spans"].append(copy.deepcopy(draft["spans"][0]))
    elif defect == "orphan":
        draft["events"] = []
    else:
        draft["events"].append(copy.deepcopy(draft["events"][0]))
    with pytest.raises(ValueError):
        parse_proposal(notice, json.dumps(draft))


def test_ambiguous_quotes_and_unicode_offsets(notices):
    text = "📌 Nộp đơn rồi Nộp đơn."
    notice = notices[0].model_copy(update={"text": text, "sentences": segment_sentences(text)})
    draft = {
        "spans": [{"span_id": "a", "label": "ACTION", "sentence_id": "s1", "text": "Nộp đơn"}],
        "events": [{"event_id": "e", "action_span_id": "a", "arguments": []}],
    }
    with pytest.raises(ValueError, match="ambiguous"):
        parse_proposal(notice, json.dumps(draft))
    draft["spans"][0]["occurrence"] = 1
    parsed = parse_proposal(notice, json.dumps(draft))
    assert parsed.spans[0].start == text.rindex("Nộp đơn")
    assert text[parsed.spans[0].start : parsed.spans[0].end] == "Nộp đơn"
    with pytest.raises(ValueError, match="JSON"):
        parse_proposal(notice, "not JSON")
    assert parse_proposal(notice, '{"spans":[],"events":[]}').events == []


def test_real_notices_require_approval_for_exact_text_and_provider(notices):
    notice = notices[0].model_copy(update={"synthetic": False})
    approval = {
        "doc_id": notice.doc_id,
        "text_sha256": text_sha256(notice),
        "reviewer_id": "reviewer-1",
        "reviewed_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "providers": ["gemini"],
        "privacy_cleared": True,
        "provider_use_approved": True,
    }
    require_provider_approval(notice, "gemini", [approval])
    for changed in [
        {"text_sha256": "0" * 64},
        {"privacy_cleared": False},
        {"provider_use_approved": False},
        {"reviewed_at": "2026-01-01T00:00:00"},
        {"reviewed_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    ]:
        with pytest.raises(ValueError, match="approval"):
            require_provider_approval(notice, "gemini", [{**approval, **changed}])
    with pytest.raises(ValueError, match="approval"):
        require_provider_approval(notice, "featherless", [approval])


def payload(provider, content, finish=None):
    if provider == "gemini":
        return {
            "candidates": [
                {"finishReason": finish or "STOP", "content": {"parts": [{"text": content}]}}
            ]
        }
    return {"choices": [{"finish_reason": finish or "stop", "message": {"content": content}}]}


@pytest.mark.parametrize("provider", ["gemini", "featherless"])
def test_provider_contract_with_mocked_http(notices, provider, monkeypatch):
    monkeypatch.setenv("GEMINI_KEY", "test-key")
    monkeypatch.setenv("FEATHERLESS_KEY", "test-key")
    content = '{"spans":[],"events":[]}'

    def respond(request):
        body = json.loads(request.content)
        if provider == "gemini":
            assert request.headers["x-goog-api-key"] == "test-key"
            assert body["generationConfig"]["responseMimeType"] == "application/json"
        else:
            assert request.headers["Authorization"] == "Bearer test-key"
            assert body["model"] == "test-model"
        assert b"source_ref" not in request.content
        return httpx.Response(200, json=payload(provider, content))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert (
            generate_draft(notices[0], provider=provider, model="test-model", client=client)
            == content
        )


@pytest.mark.parametrize("status,finish", [(429, None), (200, "length")])
def test_provider_errors_do_not_log_keys_or_response_bodies(notices, monkeypatch, status, finish):
    monkeypatch.setenv("FEATHERLESS_KEY", "do-not-log-key")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status, json=payload("featherless", "private response", finish)
            )
        )
    ) as client:
        with pytest.raises(ValueError) as error:
            generate_draft(notices[0], provider="featherless", model="test-model", client=client)
    assert "private response" not in str(error.value)
    assert "do-not-log-key" not in str(error.value)


def test_env_loading_uses_user_names_and_preserves_process_values(tmp_path, monkeypatch):
    for name in ["GEMINI_KEY", "GEMINI_MODEL", "FEATHERLESS_KEY", "FEATHERLESS_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "process-model")
    path = tmp_path / ".env"
    path.write_text(
        'GEMINI_MODEL="file-model"\nGEMINI_KEY="fake-key"\n'
        "FEATHERLESS_MODEL=org/model # comment\nFEATHERLESS_KEY='fake-key'\n",
        encoding="utf-8",
    )
    load_local_env(path)
    assert configured_model("gemini") == "process-model"
    assert configured_model("featherless") == "org/model"


def test_review_requires_completion_and_retains_safe_reviewer_identity(example):
    notice, _, original = example
    task = copy.deepcopy(original)
    assert "annotations" not in task
    with pytest.raises(ValueError, match="human annotation"):
        import_reviewed_tasks([task], [notice], [original])
    task["annotations"] = [
        {
            "completed_by": {"id": 42, "email": "private@example.invalid"},
            "result": task["predictions"][0]["result"],
        }
    ]
    imported, reviews = import_reviewed_tasks([task], [notice], [original])
    assert imported[0].annotator_id == "42"
    assert reviews[0]["decision"] == "accepted"
    assert reviews[0]["annotation_sha256"]
    assert "private@example.invalid" not in json.dumps(reviews)
    task["annotations"][0]["result"][0]["value"]["start"] += 1
    with pytest.raises(ValueError, match="offset"):
        import_reviewed_tasks([task], [notice], [original])


def test_review_logs_edits_skips_and_rejects_changed_originals(example):
    notice, _, original = example
    task = copy.deepcopy(original)
    task["annotations"] = [
        {"completed_by": "reviewer-1", "result": copy.deepcopy(task["predictions"][0]["result"])}
    ]
    link = next(r for r in task["annotations"][0]["result"] if r.get("labels") == ["DEADLINE"])
    link["labels"] = ["EVENT_TIME"]
    _, reviews = import_reviewed_tasks([task], [notice], [original])
    assert reviews[0]["decision"] == "edited"
    task["annotations"][0]["was_cancelled"] = True
    imported, reviews = import_reviewed_tasks([task], [notice], [original])
    assert imported == []
    assert reviews[0]["decision"] == "skipped"
    original["predictions"][0]["result"][0]["value"]["start"] += 1
    with pytest.raises(ValueError, match="prediction changed"):
        import_reviewed_tasks([task], [notice], [original])


def test_review_rejects_empty_exports_and_duplicate_notice_inputs(example):
    notice, _, original = example
    with pytest.raises(ValueError, match="review tasks"):
        import_reviewed_tasks([], [notice], [original])
    task = copy.deepcopy(original)
    task["annotations"] = [{"completed_by": 42, "result": task["predictions"][0]["result"]}]
    with pytest.raises(ValueError, match="unique"):
        import_reviewed_tasks([task], [notice, notice], [original])


@pytest.mark.parametrize("defect", ["reviewer", "text", "provenance"])
def test_review_rejects_missing_identity_or_stale_task(example, defect):
    notice, _, original = example
    task = copy.deepcopy(original)
    task["annotations"] = [{"completed_by": 42, "result": task["predictions"][0]["result"]}]
    if defect == "reviewer":
        task["annotations"][0].pop("completed_by")
    elif defect == "text":
        task["data"]["text"] += " changed"
    else:
        task["data"]["proposal"]["run_id"] = "stale-run"
    with pytest.raises(ValueError):
        import_reviewed_tasks([task], [notice], [original])


def test_batch_preserves_partial_success(example, notices, monkeypatch):
    notice, draft, _ = example
    other = next(n for n in notices if n.doc_id != notice.doc_id)
    monkeypatch.setenv("FEATHERLESS_KEY", "fake-key")
    bodies = iter([json.dumps(draft), "malformed JSON"])
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload("featherless", next(bodies)))
        )
    ) as client:
        tasks, failures = suggest_tasks(
            [notice, other], provider="featherless", model="m", approvals=[], client=client
        )
    assert [task["data"]["doc_id"] for task in tasks] == [notice.doc_id]
    assert [failure["doc_id"] for failure in failures] == [other.doc_id]


def test_batch_preflights_all_privacy_checks_before_requests(notices, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_KEY", "fake-key")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=payload("featherless", "not json"))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tasks, failures = suggest_tasks(
            notices[:2], provider="featherless", model="m", approvals=[], client=client
        )
        assert not tasks and len(failures) == 2
        calls.clear()
        real = notices[1].model_copy(update={"synthetic": False})
        with pytest.raises(ValueError, match="approval"):
            suggest_tasks(
                [notices[0], real], provider="featherless", model="m", approvals=[], client=client
            )
        assert not calls


def test_cli_exports_and_imports_reviewed_tasks(example, tmp_path, monkeypatch):
    notice, _, task = example
    notice_path = tmp_path / "notices.jsonl"
    write_jsonl(notice_path, [notice.model_dump(mode="json")])
    monkeypatch.setattr("smartnotice.cli.suggest_tasks", lambda *a, **k: ([task], []))
    prediction_path = tmp_path / "tasks.json"
    args = [
        "suggest-labels",
        "--notices",
        str(notice_path),
        "--provider",
        "gemini",
        "--model",
        "m",
        "--output",
        str(prediction_path),
    ]
    main(args)
    assert json.loads(prediction_path.read_text(encoding="utf-8")) == [task]
    with pytest.raises(SystemExit):
        main(args)
    exported = copy.deepcopy(task)
    exported["annotations"] = [{"completed_by": 42, "result": exported["predictions"][0]["result"]}]
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps([exported]), encoding="utf-8")
    output, log = tmp_path / "human.jsonl", tmp_path / "reviews.jsonl"
    main(
        [
            "import-reviewed-labels",
            "--notices",
            str(notice_path),
            "--input",
            str(export_path),
            "--predictions",
            str(prediction_path),
            "--output",
            str(output),
            "--review-log",
            str(log),
        ]
    )
    assert read_jsonl(output)[0]["annotator_id"] == "42"
    assert read_jsonl(log)[0]["decision"] == "accepted"
