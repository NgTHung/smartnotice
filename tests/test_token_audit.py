from pathlib import Path

import pytest
from smartnotice.lm_audit import (
    _aggregate_evidence,
    _finding_status,
    _preprocessing_replay_summary,
    _report_split_table,
    _select_policies,
    run_lm_audit,
)
from smartnotice.preprocessing.links import find_link_occurrences
from smartnotice.preprocessing.text_audit import scan_prepared_text
from smartnotice.preprocessing.token_audit import (
    boundary_lengths,
    co_visible,
    covered_characters,
    head_range,
    input_length,
    interval_retention,
    make_windows,
    pair_input_length,
)
from smartnotice.schemas import Notice, Sentence
from tokenizers import Tokenizer, models, pre_tokenizers
from tokenizers.processors import TemplateProcessing


def _tokenizer() -> Tokenizer:
    """Build a tiny deterministic tokenizer with pair separators for tests."""
    vocabulary = {
        "[UNK]": 0,
        "[CLS]": 1,
        "[SEP]": 2,
        "a": 3,
        "Nộp": 4,
        "prefix": 5,
        "hồ": 6,
        "sơ": 7,
        "tại": 8,
        "https://example.edu/a%2Fb?q=%41": 9,
    }
    tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.post_processor = TemplateProcessing(
        single="[CLS] $A [SEP]",
        pair="[CLS] $A [SEP] $B:1 [SEP]:1",
        special_tokens=[("[CLS]", 1), ("[SEP]", 2)],
    )
    return tokenizer


def test_boundary_probes_include_prefix_and_special_tokens():
    tokenizer = _tokenizer()
    lengths = boundary_lengths(tokenizer, "a", "prefix ", 8)
    assert lengths == {"C-1": 7, "C+0": 8, "C+1": 9}
    assert input_length(tokenizer, "prefix a a") == 5


def test_pair_budget_counts_both_inputs_and_separators():
    tokenizer = _tokenizer()
    assert pair_input_length(tokenizer, "a a", "a a a") == 8
    assert pair_input_length(tokenizer, "a a", "a a a") > input_length(tokenizer, "a a")


def test_head_and_windows_stay_within_budget_and_keep_codepoint_ranges():
    tokenizer = _tokenizer()
    text = "Nộp hồ sơ tại " + "a " * 10 + "cuối"
    full = input_length(tokenizer, "prefix " + text)
    assert full > 8
    head_tokens, start, end, retained = head_range(tokenizer, text, "prefix ", 8)
    assert head_tokens == 8
    assert start == 0 and 0 < end < len(text)
    assert retained > 0
    windows = make_windows(tokenizer, text, "prefix ", 8, overlap=0)
    assert len(windows) > 1
    assert all(window.input_tokens <= 8 for window in windows)
    assert windows[0].char_start == 0
    assert windows[-1].char_end == len(text)
    assert (
        interval_retention(0, len(text), [(w.char_start, w.char_end) for w in windows])
        == "retained"
    )
    assert not co_visible([(0, 3), (len(text) - 4, len(text))], windows)


def test_windows_progress_when_overlap_exceeds_window_width():
    windows = make_windows(_tokenizer(), "a " * 8, "", limit=5, overlap=128)
    assert len(windows) > 1
    assert all(window.token_end > window.token_start for window in windows)
    assert all(window.input_tokens <= 5 for window in windows)


def test_overlap_union_does_not_double_count_source_characters():
    assert covered_characters(0, 10, [(0, 6), (4, 10), (3, 5)]) == 10


def test_url_occurrences_keep_repeats_query_encoding_and_offsets():
    url = "HTTP://Example.EDU/a%2Fb?q=%41"
    text = f"X ({url}). then {url}"
    occurrences = find_link_occurrences(text)
    assert len(occurrences) == 2
    assert occurrences[0].value == url
    assert text[occurrences[0].start : occurrences[0].end] == url
    assert occurrences[0].canonical_key == occurrences[1].canonical_key
    assert "%2F" in occurrences[0].value and "%41" in occurrences[0].value


def test_url_retention_before_across_and_after_a_cut():
    text = "start https://example.edu/a%2Fb?q=%41 end"
    occurrence = find_link_occurrences(text)[0]
    middle = occurrence.start + (occurrence.end - occurrence.start) // 2
    assert interval_retention(occurrence.start, occurrence.end, [(0, occurrence.end)]) == "retained"
    assert interval_retention(occurrence.start, occurrence.end, [(0, middle)]) == "partial"
    assert interval_retention(occurrence.start, occurrence.end, [(0, occurrence.start)]) == "lost"


def test_url_split_across_windows_is_partial_without_one_complete_window():
    windows = [
        make_windows(_tokenizer(), "a a a a a", "", limit=5, overlap=0)[0],
        make_windows(_tokenizer(), "a a a a a", "", limit=5, overlap=0)[1],
    ]

    assert _finding_status(0, 3, windows) == "retained"
    assert _finding_status(3, 7, windows) == "partial"
    assert _finding_status(20, 24, windows) == "lost"


def test_unicode_offsets_are_python_codepoints_and_normal_text_is_not_flagged():
    text = "Nộp e\u0302\u0301 hồ sơ 📚 https://example.edu/a"
    occurrence = find_link_occurrences(text)[0]
    assert text[occurrence.start : occurrence.end] == occurrence.value
    findings = scan_prepared_text("Tiếng Việt có dấu ⚠ 📚")
    rules = {finding.rule_id for finding in findings}
    assert "unicode.invisible_or_control" not in rules
    assert "encoding.mojibake_heuristic" not in rules
    assert "unicode.non_bmp_offset_review" in rules


def test_preprocessing_suspicion_records_codepoint_and_offsets_without_snippets():
    text = "MIME-Version: 1.0\n<html>�\u200b</html>"
    findings = scan_prepared_text(text)
    rules = {finding.rule_id for finding in findings}
    assert "unicode.replacement_character" in rules
    assert "unicode.invisible_or_control" in rules
    assert "structure.html_tag_residue" in rules
    assert "structure.mime_marker_residue" in rules
    replacement = next(f for f in findings if f.rule_id == "unicode.replacement_character")
    assert text[replacement.start : replacement.end] == "�"
    assert replacement.codepoint == "U+FFFD"


def test_no_annotations_are_marked_not_evaluable():
    rows = _aggregate_evidence(
        annotations={},
        notice_by_id={},
        split_by_id={},
        windows_by_key={},
        model_specs=[{"key": "bami", "model_id": "test", "revision": "rev"}],
        template_ids=["text_only_v1"],
    )
    assert rows
    assert {row["status"] for row in rows} == {"not_evaluable"}


def test_policy_selection_uses_train_validation_and_ties_by_input_cost():
    policies = [
        "keep_if_fits",
        "simulated_head_truncation",
        "token_windows_overlap_0",
        "token_windows_overlap_64",
        "token_windows_overlap_128",
    ]
    summary = []
    coverage = [0.5, 0.6, 1.0, 1.0, 1.0]
    costs = [100, 200, 500, 800, 1000]
    for policy, char_coverage, cost in zip(policies, coverage, costs, strict=True):
        base = {
            "model_key": "bami",
            "template_id": "text_only_v1",
            "policy": policy,
            "source_type": "email",
            "split": "validation",
            "synthetic": False,
            "documents": 10,
            "source_characters_total": 100,
            "source_characters_visible": int(100 * char_coverage),
            "input_tokens_total": cost,
            "window_count": 10,
        }
        summary.append(base)
        summary.append(
            {**base, "split": "test", "source_characters_visible": 100, "input_tokens_total": 1}
        )
    selected = _select_policies(summary, url_rows=[], evidence_rows=[])
    assert selected["bami"]["selected_policy"] == "token_windows_overlap_0"
    assert selected["bami"]["selection_scope"]["splits"] == ["train", "validation"]


def test_existing_output_is_never_overwritten(tmp_path: Path):
    output = tmp_path / "existing-run"
    output.mkdir()
    sentinel = output / "baseline.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        run_lm_audit(
            [],
            annotations_path=None,
            reference_splits_path=None,
            output_dir=output,
            run_id="existing-run",
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_preprocessing_replay_surfaces_missing_attachment_metadata():
    text = "https://example.edu/notices"
    current = Notice(
        doc_id="a" * 20,
        source_type="email",
        source_ref="synthetic://notice",
        raw_sha256="b" * 64,
        reference_date_origin="missing",
        text=text,
        attachments=[],
        sentences=[Sentence(sentence_id="s1", start=0, end=len(text), text=text)],
        group_id="g1",
        redaction_count=0,
    )
    replay = current.model_copy(update={"attachments": [text]})

    summary = _preprocessing_replay_summary([current], [replay])

    assert summary["metadata_attachments_matches"] == 0
    assert summary["replay_attachment_entries"] == 1
    assert summary["snapshot_empty_attachment_doc_ids"] == [current.doc_id]
    assert summary["attachment_mismatch_doc_ids"] == [current.doc_id]


def test_report_split_table_separates_sources_and_empty_domain_test():
    model = {"key": "bami", "limit": 2048}
    token_rows = [
        {
            "model_key": "bami",
            "template_id": "text_only_v1",
            "source_type": "email",
            "split": "validation",
            "synthetic": False,
            "input_tokens": 2048,
            "overflow": False,
        }
    ]
    summaries = [
        {
            "model_key": "bami",
            "template_id": "text_only_v1",
            "source_type": "email",
            "split": "validation",
            "synthetic": False,
            "policy": "simulated_head_truncation",
            "partial_documents": 0,
            "unhandled_overflow_documents": 0,
        },
        {
            "model_key": "bami",
            "template_id": "text_only_v1",
            "source_type": "email",
            "split": "validation",
            "synthetic": False,
            "policy": "keep_if_fits",
            "partial_documents": 0,
            "unhandled_overflow_documents": 0,
        },
    ]

    table = _report_split_table([model], token_rows, summaries, [])

    assert "| bami · C=2,048 | email | validation | 1 | 2048 | 0/1 |" in table
    assert "| bami · C=2,048 | web | domain_test | 0 | — | 0/0 |" in table
