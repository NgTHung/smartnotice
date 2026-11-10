import hashlib

import pytest
from smartnotice.io import write_jsonl
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.split import split_documents
from smartnotice.quality import quality_summary


def test_prepared_corpus_preserves_privacy_and_group_evidence(notices):
    assert len(notices) == 9
    assert all(n.synthetic and n.privacy_review_required for n in notices)
    assert all("example.invalid" not in n.text for n in notices)
    assert all(n.source_ref.startswith("local:") for n in notices if n.source_type == "email")
    assert all(n.reference_date is not None for n in notices)
    assert all(n.text[s.start : s.end] == s.text for n in notices for s in n.sentences)


def test_manifest_path_cannot_escape_source_root(tmp_path):
    source = tmp_path / "outside.eml"
    source.write_text("Notice", encoding="utf-8")
    manifest = tmp_path / "raw/manifest.jsonl"
    write_jsonl(manifest, [{"path": "../outside.eml", "source_type": "email"}])
    with pytest.raises(ValueError, match="leaves"):
        prepare(manifest, tmp_path / "output.jsonl")


def test_content_hash_uses_unchanged_raw_bytes(tmp_path):
    raw = b"Content-Type: text/plain; charset=utf-8\n\nNotice."
    (tmp_path / "notice.eml").write_bytes(raw)
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [{"path": "notice.eml", "source_type": "email"}])
    result = prepare(manifest, tmp_path / "output.jsonl")
    assert result[0].raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert (tmp_path / "notice.eml").read_bytes() == raw
    assert result[0].reference_date is None


@pytest.mark.parametrize(
    "candidate,status",
    [
        ("2026-11-06", "unverified"),
        (None, "missing"),
        (None, "invalid"),
        ("2026-11-06", "conflict"),
    ],
)
def test_prepare_preserves_publication_evidence_without_promoting_it(tmp_path, candidate, status):
    (tmp_path / "notice.html").write_text("<article>Notice.</article>", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(
        manifest,
        [
            {
                "path": "notice.html",
                "source_type": "web",
                "source_ref": "https://example.invalid/1",
                "publication_date_candidate": candidate,
                "publication_date_status": status,
            }
        ],
    )
    notice = prepare(manifest, tmp_path / "output.jsonl")[0].model_dump(mode="json")
    assert notice["publication_date_candidate"] == candidate
    assert "publication_date_status" not in notice
    assert notice["reference_date"] is None
    assert notice["reference_date_origin"] == "missing"


def test_splits_are_repeatable_and_never_leak_groups(notices):
    assignments = split_documents(notices)
    assert assignments == split_documents(list(reversed(notices)))[::-1]
    assert quality_summary(notices, assignments)["split_group_leaks"] == []
    assert set(row["split"] for row in assignments) == {
        "train",
        "validation",
        "test",
        "domain_test",
    }
    assert len({row["group_id"] for row in assignments}) < len(notices)


def test_holdout_group_excludes_related_email(notices):
    selected = [notices[0].model_copy(deep=True), notices[-1].model_copy(deep=True)]
    selected[1].domain_holdout = True
    selected[1].group_id = selected[0].group_id
    assignments = split_documents(selected)
    assert [row["split"] for row in assignments] == ["excluded", "domain_test"]
    assert quality_summary(selected, assignments)["split_group_leaks"] == []


def test_small_corpus_does_not_duplicate_documents_to_fill_splits(notices):
    assert [row["split"] for row in split_documents(notices[:1])] == ["train"]
    with pytest.raises(ValueError, match="unique"):
        split_documents([notices[0], notices[0]])
    with pytest.raises(ValueError, match="Similarity"):
        split_documents(notices, similarity=0)


def test_quality_rejects_duplicate_assignments(notices):
    assignments = split_documents(notices)
    with pytest.raises(ValueError, match="unique document"):
        quality_summary(notices, [*assignments, assignments[0]])
