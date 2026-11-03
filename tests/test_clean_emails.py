"""MIME regressions adapted from Data Email/test_clean_emails.py; synthetic inputs."""

from email.message import EmailMessage

import pytest
from smartnotice.parsers.email import parse_email, parse_email_details
from smartnotice.preprocessing.text import normalize_text


@pytest.mark.parametrize("encoding", ["base64", "quoted-printable"])
def test_vietnamese_transfer_encodings(encoding):
    mail = EmailMessage()
    mail.set_content("Học bổng – đăng ký trước 27/09/2026.", cte=encoding)
    assert parse_email(mail.as_bytes())[0] == "Học bổng – đăng ký trước 27/09/2026."


def test_control_characters_bullets_and_mbox_escaped_from():
    text = "Cha\u0300o\u200b em\r\r\n\r\r\n *\r\r\n  Học\xa0bổng\x00\ue117\r\r\n[cid:logo]"
    assert normalize_text(text) == "Chào em\n\n- Học bổng"
    assert (
        normalize_text(">From the Foundations\nGPA ≥ 3.2; 📌")
        == "From the Foundations\nGPA ≥ 3.2; 📌"
    )


def test_invalid_charset_is_recovered_with_safe_warning():
    raw = b'Content-Type: text/plain; charset="unknown-codec"\n\n' + "Thông báo".encode()
    parsed = parse_email_details(raw)
    assert parsed.text == "Thông báo"
    assert "charset_fallback" in parsed.warnings
    assert "unknown-codec" not in str(parsed.warnings)


def test_replacement_character_is_reported_and_missing_date_stays_missing():
    mail = EmailMessage()
    mail["Date"] = "not a date"
    mail.set_content("Tên: Nguy�n")
    parsed = parse_email_details(mail.as_bytes())
    assert parsed.reference_date is None
    assert "replacement_character_in_content" in parsed.warnings


def test_text_and_message_attachments_are_excluded():
    mail = EmailMessage()
    mail.set_content("Nội dung chính")
    mail.add_attachment("Secret attachment", filename="notes.txt")
    nested = EmailMessage()
    nested.set_content("Attached email body")
    mail.add_attachment(nested, filename="forwarded.eml")
    assert parse_email(mail.as_bytes())[0] == "Nội dung chính"


def test_related_mime_uses_root_content_id():
    mail = EmailMessage()
    mail.make_related()
    mail.set_param("start", "<root>")
    for cid, text in [("<extra>", "Auxiliary resource"), ("<root>", "Main HTML")]:
        part = EmailMessage()
        part.set_content(f"<p>{text}</p>", subtype="html")
        part["Content-ID"] = cid
        mail.attach(part)
    assert parse_email(mail.as_bytes())[0] == "Main HTML"


def test_html_hides_preheaders_and_preserves_table_evidence():
    mail = EmailMessage()
    mail.set_content(
        '<p>Học <b>bổng</b></p><div style="display: none">Hidden</div>'
        "<p hidden>Also hidden</p><script>secret()</script>"
        "<table><tr><th>Việc</th><th>Hạn chót</th></tr>"
        "<tr><td>Hồ sơ</td><td>30/10/2026</td></tr></table>",
        subtype="html",
    )
    text, _, _ = parse_email(mail.as_bytes())
    assert "Học bổng" in text and "Việc: Hồ sơ; Hạn chót: 30/10/2026" in text
    assert all(item not in text for item in ["Hidden", "hidden", "secret"])


def test_footer_removed_but_registration_url_survives():
    mail = EmailMessage()
    mail.set_content(
        "Đăng ký https://example.invalid/apply\n\n-----\n"
        "This is a copy of a message posted in COURSE.\nPreferences"
    )
    assert parse_email(mail.as_bytes())[0] == "Đăng ký https://example.invalid/apply"
