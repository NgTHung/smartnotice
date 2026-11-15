"""Verify the shipped snapshot and reject corruption without local crawl files."""

import json
import shutil
from pathlib import Path

import pytest
from smartnotice.collectors.dataset import validate_team_snapshot
from smartnotice.io import read_jsonl, write_jsonl


@pytest.fixture
def snapshot(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data/catalogs/hcmus-focused-100"
    for filename in [
        "notices.jsonl",
        "snapshot_index.jsonl",
        "snapshot_summary.json",
        "sources.jsonl",
    ]:
        shutil.copyfile(source / filename, tmp_path / filename)
    return tmp_path


def test_shipped_snapshot_validates_without_raw_or_network(snapshot):
    report = validate_team_snapshot(snapshot)
    assert report["institutions"] == {"HCMUS": 40, "UIT": 30, "UEH": 30}
    assert report["validated_documents"] == report["unique_prepared_texts"] == 100
    assert report["human_privacy_review_complete"] is False
    assert not (snapshot / "raw").exists()


def test_snapshot_accepts_a_different_release_size_and_can_pin_the_total(snapshot):
    index = read_jsonl(snapshot / "snapshot_index.jsonl")[:1]
    row = index[0]
    summary_path = snapshot / "snapshot_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        documents=1,
        institutions={row["institution"]: 1},
        additional_redactions=row["additional_redactions"],
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    for name in ("notices.jsonl", "snapshot_index.jsonl", "sources.jsonl"):
        path = snapshot / name
        write_jsonl(path, [r for r in read_jsonl(path) if r["doc_id"] == row["doc_id"]])
    assert validate_team_snapshot(snapshot, expected_documents=1)["validated_documents"] == 1
    with pytest.raises(ValueError, match="summary counts"):
        validate_team_snapshot(snapshot, expected_documents=100)


def test_shared_notices_include_unverified_publication_dates(snapshot):
    index = {row["doc_id"]: row for row in read_jsonl(snapshot / "snapshot_index.jsonl")}
    for notice in read_jsonl(snapshot / "notices.jsonl"):
        source = index[notice["doc_id"]]
        assert notice["publication_date_candidate"] == source["publication_date_candidate"]
        assert "publication_date_status" not in notice
        assert notice["reference_date"] is None
        assert notice["reference_date_origin"] == "missing"


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_field",
        "source",
        "missing",
        "text",
        "summary",
        "date",
        "offsets",
        "review",
        "notice_date",
        "notice_date_status",
        "missing_notice_date",
    ],
)
def test_shared_snapshot_rejects_corruption(snapshot, damage):
    index = read_jsonl(snapshot / "snapshot_index.jsonl")
    notices = read_jsonl(snapshot / "notices.jsonl")
    if damage == "unknown_field":
        index[0]["machine_local_path"] = "private/raw.html"
    elif damage == "source":
        index[0]["url"] = "https://outside.invalid/notice"
    elif damage == "missing":
        notices.pop()
    elif damage == "text":
        notices[0]["text"] += " Changed source"
    elif damage == "summary":
        p = snapshot / "snapshot_summary.json"
        summary = json.loads(p.read_text(encoding="utf-8"))
        summary["additional_redactions"] += 1
        p.write_text(json.dumps(summary), encoding="utf-8")
    elif damage == "date":
        index[0]["publication_date_candidate"] = "2000-01-01"
    elif damage == "notice_date":
        notices[0]["publication_date_candidate"] = "2000-01-01"
    elif damage == "notice_date_status":
        notices[0]["publication_date_status"] = "missing"
    elif damage == "missing_notice_date":
        notices[0].pop("publication_date_candidate", None)
    elif damage == "offsets":
        notices[0]["sentences"] = []
    else:
        notices[0]["privacy_review_required"] = False
    write_jsonl(snapshot / "snapshot_index.jsonl", index)
    write_jsonl(snapshot / "notices.jsonl", notices)
    with pytest.raises(ValueError):
        validate_team_snapshot(snapshot)
