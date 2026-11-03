"""URL cases adapted from Data Email/test_link_extraction.py, with evidence retained."""

import pytest
from smartnotice.parsers.html import parse_html
from smartnotice.preprocessing.links import extract_links
from smartnotice.preprocessing.privacy import PrivacyRules
from smartnotice.preprocessing.text import normalize_and_redact


def test_original_separation_mode_retains_labels_and_deduplicates():
    text, links = extract_links(
        "Đăng ký: Tại đây<https://example.invalid/apply>\n"
        "Chi tiết: https://example.invalid/info.\nhttps://example.invalid/apply"
    )
    assert links == ["https://example.invalid/apply", "https://example.invalid/info"]
    assert "Đăng ký: Tại đây" in text and "http" not in text and "<>" not in text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tài liệu (https://example.invalid/info).", "https://example.invalid/info"),
        ("https://example.invalid/Function_(math).", "https://example.invalid/Function_(math)"),
        ("[Tài liệu](https://example.invalid/guide)", "https://example.invalid/guide"),
        (
            "<https://example.invalid/\nregister?event=2026>",
            "https://example.invalid/register?event=2026",
        ),
        ("Xem **https://example.invalid/guide**", "https://example.invalid/guide"),
    ],
)
def test_normalized_links_remain_as_evidence(text, expected):
    prepared, links = extract_links(text, keep_in_text=True)
    assert links == [expected] and expected in prepared


@pytest.mark.parametrize(
    "link,expected",
    [
        (
            "www.example.invalid/apply?email=person%40gmail.com&event=2026",
            "www.example.invalid/apply?email=REDACTED&event=2026",
        ),
        (
            parse_html(
                '<a href="https://example.invalid/apply?event=2026&amp;token=secret">Link</a>'
            ),
            "https://example.invalid/apply?event=2026&token=REDACTED",
        ),
        (
            "<https://example.invalid/apply?to=person%40g\nmail.com>",
            "https://example.invalid/apply?to=REDACTED",
        ),
    ],
)
def test_folded_and_encoded_private_url_values_are_redacted(link, expected):
    text, _ = extract_links(link, keep_in_text=True)
    text, count = normalize_and_redact(text, privacy=PrivacyRules())
    text, links = extract_links(text, keep_in_text=True)
    assert count > 0
    assert links == [expected] and expected in text
    assert "secret" not in text and "person" not in text


def test_malformed_url_omitted_and_no_links_is_empty():
    text, links = extract_links("Email: http://([EMAIL])", keep_in_text=True)
    assert links == [] and "[LIEN_KET_KHONG_HOP_LE]" in text
    assert extract_links("Không có liên kết.")[1] == []


def test_nested_html_entities_cannot_expose_query_after_redaction():
    text, _ = extract_links(
        parse_html(
            '<a href="https://example.invalid/apply?event=2026&amp;amp;token=secret">Link</a>'
        ),
        keep_in_text=True,
    )
    text, _ = normalize_and_redact(text)
    text, links = extract_links(text, keep_in_text=True)
    assert links == ["https://example.invalid/apply?event=2026&amp;token=REDACTED"]
    assert "secret" not in text
