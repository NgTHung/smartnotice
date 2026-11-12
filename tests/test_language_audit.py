"""Check surface heuristics and label membership on synthetic documents."""

import json
from pathlib import Path

import pytest
from smartnotice.labeling.token_balance import token_label_counts
from smartnotice.language_audit import run_language_audit
from smartnotice.lm_audit import _sha256
from smartnotice.preprocessing.language_features import language_features, surface_words
from smartnotice.schemas import Annotation, Notice, Span
from tokenizers import Tokenizer, models, pre_tokenizers


def test_surface_forms_exclude_urls_and_placeholders_and_keep_offsets():
    text = (
        "SV HK ĐKHP\nsinh vien dang ky hoc phan\nĐăng ký online meeting\nTHÔNG "
        "BÁO\nthông báo\nhttps://example.edu/english/SV [NAME]"
    )
    counts, hits = language_features(text)
    assert counts["known_abbreviation"] == 3
    assert counts["english_lexicon_hit"] == 2
    assert counts["unaccented_phrase_candidate"] == 2
    assert counts["uppercase_line"] == 2
    assert counts["lowercase_line"] == 2
    assert counts["mixed_vietnamese_english_candidate"] == 1
    assert all(0 <= h.start < h.end <= len(text) for h in hits)
    assert "NAME" not in surface_words(text)
    assert "example" not in surface_words(text)


def test_ascii_and_diacritics_do_not_prove_a_language():
    counts, _ = language_features("abc xyz\nTiếng Việt có dấu\n😀 SV")
    assert counts.get("unaccented_phrase_candidate", 0) == 0
    assert counts.get("english_lexicon_hit", 0) == 0
    assert counts["ascii_only_line_candidate"] == 2


def test_token_classes_partition_overlapping_boundary_and_zero_width():
    annotation = Annotation(
        doc_id="doc",
        annotator_id="human",
        events=[],
        spans=[
            Span(span_id="a", label="ACTION", start=1, end=5, text="abcd"),
            Span(span_id="b", label="TIME", start=2, end=4, text="bc"),
        ],
    )
    counts = token_label_counts([(0, 0), (0, 2), (1, 2), (2, 3), (5, 7)], annotation)
    assert counts == {"BOUNDARY": 1, "ACTION": 1, "MULTI": 1, "O": 1}
    assert sum(counts.values()) == 4


def _jsonl(path: Path, rows: list) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_extension_inherits_hashes_split_and_excludes_unannotated_from_o(tmp_path):
    notice = Notice(
        doc_id="one",
        source_type="email",
        source_ref="synthetic",
        raw_sha256="a" * 64,
        reference_date_origin="missing",
        text="SV online",
        sentences=[],
        group_id="g",
        redaction_count=0,
        synthetic=True,
    )
    notices = tmp_path / "notices.jsonl"
    _jsonl(
        notices,
        [
            notice.model_dump(mode="json"),
            notice.model_copy(update={"doc_id": "two"}).model_dump(mode="json"),
        ],
    )
    annotations = tmp_path / "annotations.jsonl"
    _jsonl(
        annotations,
        [
            Annotation(
                doc_id="one",
                annotator_id="human",
                spans=[Span(span_id="s", label="ACTION", start=0, end=2, text="SV")],
                events=[],
            ).model_dump(mode="json")
        ],
    )
    base = tmp_path / "base"
    base.mkdir()
    (base / "run.json").write_text(
        json.dumps(
            {
                "snapshot_files": {
                    notices.name: _sha256(notices),
                    annotations.name: _sha256(annotations),
                }
            }
        )
    )
    _jsonl(
        base / "split_assignments.jsonl", [dict(doc_id=d, split="train") for d in ("one", "two")]
    )
    metadata = json.loads((base / "run.json").read_text())
    metadata["audit_split_assignments_sha256"] = _sha256(base / "split_assignments.jsonl")
    (base / "run.json").write_text(json.dumps(metadata))
    cache = tmp_path / "cache"
    path = cache / "models--test--tok" / "snapshots" / "rev"
    path.mkdir(parents=True)
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "SV": 1, "online": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.save(str(path / "tokenizer.json"))
    checks = {
        "models": [
            dict(
                model_key=k,
                model_id="test/tok",
                revision="rev",
                tokenizer_file_sha256={"tokenizer.json": _sha256(path / "tokenizer.json")},
            )
            for k in ("bami", "vit5")
        ]
    }
    (base / "model_checks.json").write_text(json.dumps(checks))
    output = tmp_path / "output"
    summary = run_language_audit([notices], annotations, base, output, cache)
    assert summary["documents"] == 2 and summary["annotated_documents"] == 1
    import csv

    rows = list(csv.DictReader((output / "token_label_balance.csv").open()))
    assert sum(int(r["count"]) for r in rows if r["model_key"] == "bami") == 2
    assert (
        next(int(r["count"]) for r in rows if r["model_key"] == "bami" and r["label"] == "O") == 1
    )
    assert {r["split"] for r in rows} == {"train"}
    assert json.loads((output / "run.json").read_text())["unannotated_status"] == "not_evaluable"
    with pytest.raises(ValueError, match="already exists"):
        run_language_audit([notices], annotations, base, output, cache)
    notices.write_text("{}\n")
    with pytest.raises(ValueError, match="does not match"):
        run_language_audit([notices], annotations, base, tmp_path / "bad", cache)
    assert not (tmp_path / "bad").exists()
