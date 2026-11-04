import unicodedata
from datetime import date
from email.message import EmailMessage

import pytest
from smartnotice.parsers.email import parse_email
from smartnotice.parsers.html import parse_html
from smartnotice.preprocessing.dates import normalize_date
from smartnotice.preprocessing.text import normalize_and_redact, segment_sentences


def test_email_mime_prefers_plain_and_removes_history():
    message = EmailMessage()
    message["Date"] = "Tue, 20 Oct 2026 09:00:00 +0700"
    message["From"] = "Private Sender <sender@example.invalid>"
    message["References"] = "<root@example.invalid> <reply@example.invalid>"
    message.set_content("Nộp hồ sơ ngày 30/10.\n> Bản cũ\n-- \nChữ ký riêng")
    message.add_alternative("<p>HTML alternative</p>", subtype="html")
    message.add_attachment(b"attachment text", maintype="application", subtype="octet-stream")
    text, reference, thread = parse_email(message.as_bytes())
    assert "Nộp hồ sơ" in text
    assert all(value not in text for value in ["Bản cũ", "Chữ ký", "Private", "alternative"])
    assert reference == date(2026, 10, 20)
    assert thread == "<root@example.invalid>"


def test_html_email_and_missing_date():
    message = EmailMessage()
    message.set_content("<p>Nộp hồ sơ</p>", subtype="html")
    text, reference, _ = parse_email(message.as_bytes())
    assert text == "Nộp hồ sơ"
    assert reference is None


def test_inline_html_preserves_phrases_and_block_boundaries():
    text = parse_html(
        "<article><p>Nộp <strong>hồ sơ</strong> trước hạn.</p><p>Nhận kết quả.</p></article>"
    )
    assert "Nộp hồ sơ trước hạn." in text
    normalized, _ = normalize_and_redact(text)
    assert len(segment_sentences(normalized)) == 2


def test_html_table_retains_date_roles_and_selected_body():
    text = parse_html(
        """<nav>MENU</nav><article><p>Nộp hồ sơ</p>
        <table><tr><th>Việc</th><th>Hạn chót</th></tr>
        <tr><td>Học bổng</td><td>30/10/2026</td></tr></table>
        <script>SECRET</script></article><aside>EXCLUDED</aside>""",
        "article",
    )
    assert "Việc: Học bổng; Hạn chót: 30/10/2026" in text
    assert all(value not in text for value in ["SECRET", "MENU", "EXCLUDED"])
    with pytest.raises(ValueError, match="selector"):
        parse_html("<p>Text</p>", ".absent")


def test_nfc_redaction_precedes_exact_sentence_offsets():
    original = "Nguyễn Văn Mẫu nộp ngày 30/10/2026.\nEmail: x@example.invalid; MSSV: 24000001."
    text, count = normalize_and_redact(unicodedata.normalize("NFD", original), ["Nguyễn Văn Mẫu"])
    assert count == 3
    assert text.startswith("[NAME]") and "[EMAIL]" in text and "[STUDENT_ID]" in text
    assert "30/10/2026" in text
    sentences = segment_sentences(text)
    assert len(sentences) == 2
    assert all(text[s.start : s.end] == s.text for s in sentences)


@pytest.mark.parametrize(
    ("value", "reference", "expected", "inferred"),
    [
        ("30/10/2026", None, date(2026, 10, 30), False),
        ("01/11", date(2026, 10, 20), date(2026, 11, 1), True),
        ("01/11", None, None, False),
        ("31/02/2026", None, None, False),
        ("thứ Sáu tuần này", date(2026, 10, 20), None, False),
    ],
)
def test_numeric_date_normalization(value, reference, expected, inferred):
    assert normalize_date(value, reference) == (expected, inferred)


def test_segmentation_keeps_titles_and_list_markers_with_their_text():
    text = (
        "1. Liên hệ PGS.TS. Mai tại TP. Hồ Chí Minh. Nộp đơn.\na. Đóng phí!\n*2. Họp ở phòng 1. Về."
    )
    sentences = segment_sentences(text)
    assert [s.text for s in sentences] == [
        "1. Liên hệ PGS.TS. Mai tại TP. Hồ Chí Minh.",
        "Nộp đơn.",
        "a. Đóng phí!",
        "*2. Họp ở phòng 1.",
        "Về.",
    ]
    assert all(text[s.start : s.end] == s.text for s in sentences)
