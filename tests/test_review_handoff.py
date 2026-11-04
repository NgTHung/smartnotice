"""Check the handoff from prepared notices to human review and model suggestions."""

import json
from datetime import UTC, datetime

import pytest
from smartnotice.cli import main
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.llm import text_sha256


def _approval(notice, *, privacy=True, provider=False, providers=()):
    return {
        "doc_id": notice.doc_id,
        "text_sha256": text_sha256(notice),
        "reviewer_id": "reviewer-1",
        "reviewed_at": datetime(2026, 11, 1, tzinfo=UTC).isoformat(),
        "providers": list(providers),
        "privacy_cleared": privacy,
        "provider_use_approved": provider,
    }


@pytest.fixture
def corpus(notices, tmp_path):
    real = [notice.model_copy(update={"synthetic": False}) for notice in notices[:3]]
    path = tmp_path / "notices.jsonl"
    write_jsonl(path, [notice.model_dump(mode="json") for notice in real])
    return real, path


def _export(path, approvals, output):
    main(
        [
            "export-tasks",
            "--notices",
            str(path),
            "--approvals",
            str(approvals),
            "--output",
            str(output),
        ]
    )
    return [task["data"]["doc_id"] for task in json.loads(output.read_text(encoding="utf-8"))]


def _queue(path, approvals, output):
    main(
        [
            "privacy-review-queue",
            "--notices",
            str(path),
            "--approvals",
            str(approvals),
            "--output",
            str(output),
        ]
    )
    return read_jsonl(output)


def _suggest(path, approvals, *extra):
    main(
        [
            "suggest-labels",
            "--notices",
            str(path),
            "--provider",
            "gemini",
            "--model",
            "m",
            "--approvals",
            str(approvals),
            "--output",
            str(approvals.parent / "new.json"),
            "--dry-run",
            *extra,
        ]
    )


def test_queue_lists_only_unreviewed_real_text_with_an_unusable_template(corpus, tmp_path):
    real, path = corpus
    approvals = tmp_path / "approvals.jsonl"
    write_jsonl(approvals, [_approval(real[0])])
    rows = _queue(path, approvals, tmp_path / "queue.jsonl")
    assert [row["doc_id"] for row in rows] == [real[1].doc_id, real[2].doc_id]
    assert rows[0]["text"] == real[1].text
    assert rows[0]["approval"]["text_sha256"] == text_sha256(real[1])
    assert rows[0]["approval"]["reviewer_id"] == ""
    assert rows[0]["approval"]["privacy_cleared"] is False


def test_queue_refuses_to_replace_the_approval_ledger(corpus, tmp_path):
    real, path = corpus
    approvals = tmp_path / "approvals.jsonl"
    write_jsonl(approvals, [_approval(real[0])])
    with pytest.raises(SystemExit):
        _queue(path, approvals, approvals)
    assert read_jsonl(approvals)[0]["reviewer_id"] == "reviewer-1"


def test_unfilled_queue_template_never_authorizes_export(corpus, tmp_path):
    _, path = corpus
    approvals = tmp_path / "approvals.jsonl"
    rows = _queue(path, tmp_path / "missing.jsonl", tmp_path / "queue.jsonl")
    write_jsonl(approvals, [rows[0]["approval"]])
    with pytest.raises(SystemExit):
        _export(path, approvals, tmp_path / "tasks.json")
    assert not (tmp_path / "tasks.json").exists()


def test_export_holds_unreviewed_and_stale_text(corpus, tmp_path, capsys):
    real, path = corpus
    stale = {**_approval(real[1]), "text_sha256": "0" * 64}
    approvals = tmp_path / "approvals.jsonl"
    write_jsonl(approvals, [_approval(real[0]), stale])
    assert _export(path, approvals, tmp_path / "tasks.json") == [real[0].doc_id]
    assert "held 2" in capsys.readouterr().out


def test_export_refuses_to_write_when_nothing_is_cleared(corpus, tmp_path):
    _, path = corpus
    with pytest.raises(SystemExit):
        _export(path, tmp_path / "missing.jsonl", tmp_path / "tasks.json")
    assert not (tmp_path / "tasks.json").exists()


def test_privacy_only_review_does_not_authorize_a_provider(corpus, tmp_path):
    real, path = corpus
    approvals = tmp_path / "approvals.jsonl"
    write_jsonl(approvals, [_approval(real[0])])
    with pytest.raises(SystemExit):
        _suggest(path, approvals, "--doc-id", real[0].doc_id)


def test_suggest_selects_failure_ledgers_and_splits(corpus, tmp_path, capsys):
    real, path = corpus
    approvals = tmp_path / "approvals.jsonl"
    write_jsonl(approvals, [_approval(n, provider=True, providers=["gemini"]) for n in real])
    ledger = tmp_path / "failed.jsonl"
    write_jsonl(ledger, [{"doc_id": real[1].doc_id, "reason": "gemini HTTP 429"}])
    _suggest(path, approvals, "--selection", str(ledger))
    assert json.loads(capsys.readouterr().out)["doc_ids"] == [real[1].doc_id]
    splits = tmp_path / "splits.jsonl"
    write_jsonl(
        splits,
        [
            {"doc_id": real[0].doc_id, "split": "train"},
            {"doc_id": real[1].doc_id, "split": "test"},
            {"doc_id": real[2].doc_id, "split": "train"},
        ],
    )
    _suggest(path, approvals, "--selection", str(splits), "--split", "train")
    assert json.loads(capsys.readouterr().out)["doc_ids"] == sorted(
        [real[0].doc_id, real[2].doc_id]
    )


def test_split_filter_requires_a_selection_file(corpus, tmp_path):
    _, path = corpus
    with pytest.raises(SystemExit):
        _suggest(path, tmp_path / "missing.jsonl", "--split", "train")


def test_approved_only_skips_unapproved_real_notices(corpus, tmp_path, capsys):
    real, path = corpus
    approvals = tmp_path / "approvals.jsonl"
    write_jsonl(
        approvals,
        [_approval(real[0], provider=True, providers=["gemini"]), _approval(real[1])],
    )
    with pytest.raises(SystemExit):
        _suggest(path, approvals)
    capsys.readouterr()
    _suggest(path, approvals, "--approved-only")
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["doc_ids"] == [real[0].doc_id]
