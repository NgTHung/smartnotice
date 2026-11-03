"""Synthetic regression cases adapted from the supplied Data Email cleaner tests."""

import hashlib
import json
from datetime import date
from email.message import EmailMessage

import pytest
from smartnotice.collectors.local import collect_email
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.studio import export_tasks
from smartnotice.parsers.email import parse_email
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.schemas import Notice


def email_bytes(body: str, *, html: bool = False) -> bytes:
    mail = EmailMessage()
    mail["From"] = "Office <office@example.invalid>"
    mail["Date"] = "Tue, 20 Oct 2026 09:00:00 +0700"
    mail["Message-ID"] = "<notice@example.invalid>"
    mail.set_content(body, subtype="html" if html else "plain")
    return mail.as_bytes()


def test_empty_plain_body_falls_back_to_html():
    mail = EmailMessage()
    mail.set_content(" ")
    mail.add_alternative("<p>Thông báo học bổng</p>", subtype="html")
    assert parse_email(mail.as_bytes())[0] == "Thông báo học bổng"


def test_inline_and_bottom_posted_reply_keeps_new_contributions():
    body = "On Monday, A <a@example.invalid> wrote:\n> Câu hỏi 1\nTrả lời 1\n> Câu hỏi 2\nTrả lời 2"
    text, _, _ = parse_email(email_bytes(body))
    assert "Trả lời 1" in text and "Trả lời 2" in text
    assert "Câu hỏi" not in text


def test_prepare_keeps_private_safe_urls_in_text_and_attachments(tmp_path):
    raw = email_bytes(
        "<p>Đăng ký trước 30/10/2026: "
        '<a href="https://example.invalid/apply?event=2026&amp;email=user%40gmail.com'
        '&amp;token=secret">Biểu mẫu</a></p>'
        "<p hidden>Hidden preheader</p>",
        html=True,
    )
    path = tmp_path / "notice.eml"
    path.write_bytes(raw)
    collect_email(path, tmp_path / "raw", "consent-synthetic", None)
    output = tmp_path / "notices.jsonl"
    notice = prepare(tmp_path / "raw/manifest.jsonl", output)[0]
    url = "https://example.invalid/apply?event=2026&email=REDACTED&token=REDACTED"
    assert notice.attachments == [url]
    assert url in notice.text and "Biểu mẫu" in notice.text
    assert all(value not in notice.text for value in ["user", "secret", "Hidden preheader"])
    assert notice.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert notice.doc_id == notice.raw_sha256[:20]
    assert notice.reference_date == date(2026, 10, 20)
    assert notice.group_id == hashlib.sha256(b"<notice@example.invalid>").hexdigest()[:20]
    assert all(notice.text[s.start : s.end] == s.text for s in notice.sentences)
    assert Notice.model_validate(read_jsonl(output)[0]) == notice
    assert path.read_bytes() == raw
    task = export_tasks([notice])[0]["data"]
    assert task["attachments"] == [url] and task["privacy_review_required"]
    invalid = notice.model_dump()
    invalid["attachments"] = ["https://example.invalid/unsupported"]
    with pytest.raises(ValueError, match="prepared text"):
        Notice.model_validate(invalid)


def test_invalid_source_does_not_replace_previous_output(tmp_path):
    (tmp_path / "notice.eml").write_bytes(email_bytes("Nội dung hợp lệ."))
    (tmp_path / "empty.eml").write_bytes(email_bytes(" "))
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(
        manifest,
        [
            {"path": "notice.eml", "source_type": "email"},
            {"path": "empty.eml", "source_type": "email"},
        ],
    )
    output = tmp_path / "notices.jsonl"
    output.write_text("previous output\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Manifest line 2"):
        prepare(manifest, output)
    assert output.read_text(encoding="utf-8") == "previous output\n"


def test_legacy_policy_requires_explicit_selection(tmp_path):
    path = tmp_path / "notice.eml"
    path.write_bytes(email_bytes("Liên hệ: office@example.invalid; learner@gmail.com"))
    collect_email(path, tmp_path / "raw", "consent-synthetic", None)
    config = tmp_path / "privacy.json"
    config.write_text(json.dumps({"public_emails": []}), encoding="utf-8")
    manifest = tmp_path / "raw/manifest.jsonl"
    strict = prepare(manifest, tmp_path / "strict.jsonl", privacy_rules=config)[0]
    legacy = prepare(
        manifest, tmp_path / "legacy.jsonl", privacy_rules=config, email_policy="legacy"
    )[0]
    assert "office@example.invalid" not in strict.text
    assert "office@example.invalid" in legacy.text
    assert "learner@gmail.com" not in legacy.text
    assert legacy.privacy_rules_sha256 == hashlib.sha256(config.read_bytes()).hexdigest()
    assert strict.email_policy == "all" and legacy.email_policy == "legacy"
    assert strict.privacy_review_required and legacy.privacy_review_required


def test_older_notices_load_without_new_metadata(notices):
    row = notices[0].model_dump()
    for key in ["attachments", "parser_warnings", "email_policy", "privacy_rules_sha256"]:
        row.pop(key)
    notice = Notice.model_validate(row)
    assert notice.attachments == [] and notice.parser_warnings == []
    assert notice.email_policy == "all" and notice.privacy_rules_sha256 is None


def test_name_learning_is_local_to_each_source(tmp_path):
    original = tmp_path / "original.eml"
    original.write_bytes(email_bytes("Mời Nguyễn Văn Mẫu đến văn phòng."))
    collect_email(original, tmp_path / "raw", "consent-synthetic", None)
    manifest = tmp_path / "raw/manifest.jsonl"
    alone = prepare(manifest, tmp_path / "alone.jsonl")[0]
    reply = EmailMessage()
    reply["From"] = "Nguyễn Văn Mẫu <24129999@student.hcmus.edu.vn>"
    reply.set_content("Em đã nhận.")
    other = tmp_path / "other.eml"
    other.write_bytes(reply.as_bytes())
    collect_email(other, tmp_path / "raw", "consent-synthetic", None)
    together = prepare(manifest, tmp_path / "together.jsonl")
    assert together[0] == alone
