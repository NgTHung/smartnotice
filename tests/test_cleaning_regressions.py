"""Synthetic regressions for source boundaries, privacy, and URL evidence."""

import csv
import hashlib
import unicodedata
from collections import Counter
from email.message import EmailMessage

import pytest
from smartnotice.cli import main
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.studio import export_tasks, import_tasks
from smartnotice.parsers.email import parse_email
from smartnotice.parsers.html import parse_html
from smartnotice.parsers.thread import email_from_text, split_thread
from smartnotice.preprocessing.links import extract_links
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.privacy import PrivacyRules
from smartnotice.preprocessing.privacy_audit import audit_email_policy
from smartnotice.preprocessing.text import normalize_and_redact


def _email(body: str, *, html: bool = False) -> bytes:
    mail = EmailMessage()
    mail.set_content(body, subtype="html" if html else "plain")
    return mail.as_bytes()


@pytest.mark.parametrize("identifier", ["20120318", "19120105", "24129999"])
def test_date_shaped_student_ids_need_explicit_date_context(identifier):
    rules = PrivacyRules()
    assert rules.redact(identifier, Counter()) == "[STUDENT_ID]"
    assert "[STUDENT_ID]" in rules.redact(f"student ID: {identifier}", Counter())


def test_date_context_does_not_override_student_or_birthdate_labels():
    text, _ = normalize_and_redact(
        "Ngày thông báo: 20261107; hạn nộp 20261108.\nNgày sinh: 20120318; MSSV: 19120105."
    )
    assert "20261107" in text and "20261108" in text
    assert "20120318" not in text and "19120105" not in text
    assert "[NGAY_SINH]" in text


@pytest.mark.parametrize(
    "quote",
    [
        '<div class="gmail_quote">THIRD_PARTY</div>',
        '<blockquote type="cite">THIRD_PARTY</blockquote>',
        '<table><tr><td><div class="extra gmail_quote">THIRD_PARTY</div></td></tr></table>',
    ],
)
def test_html_table_quotes_are_removed_before_flattening(quote):
    text, _, _ = parse_email(
        _email(f"<table><tr><td>Thông báo mới{quote}Hạn 07/11/2026</td></tr></table>", html=True)
    )
    assert "Thông báo mới" in text and "07/11/2026" in text
    assert "THIRD_PARTY" not in text and "[[EMAIL_QUOTE_" not in text


@pytest.mark.parametrize("html", [False, True])
def test_literal_quote_markers_are_content(html):
    body = "Phần đầu\n[[EMAIL_QUOTE_START]]\nNội dung thật\n[[EMAIL_QUOTE_END]]\nPhần cuối"
    if html:
        body = "<p>" + body.replace("\n", "</p><p>") + "</p>"
    text, _, _ = parse_email(_email(body, html=html))
    assert "Nội dung thật" in text and "Phần cuối" in text


@pytest.mark.parametrize(
    "separator",
    [
        "Original Message",
        "- Original Message -",
        "----- Original Message -----",
        "_____ Original Message _____",
        "— Original Message —",
    ],
)
def test_original_message_delimiters(separator):
    parts = split_thread(
        f"Phần mới\n{separator}\nFrom: A <a@example.invalid>\nSubject: Cũ\n\nPhần cũ", ""
    )
    assert parts[0].body == "Phần mới"
    assert parts[1].body == "Phần cũ"


def test_original_message_inside_a_sentence_is_content():
    text = "Xem Original Message để biết thêm\nHạn nộp 07/11/2026"
    assert split_thread(text, "")[0].body == text


@pytest.mark.parametrize("separator", ["Original Message", "- Original Message -"])
def test_original_message_line_without_recovered_headers(separator):
    assert split_thread(f"Phần mới\n{separator}\nPhần cũ", "")[0].body == "Phần mới"


@pytest.mark.parametrize("wrapper", ["*", "**", "'", "=", "/", "_", "("])
@pytest.mark.parametrize("policy", ["all", "legacy"])
def test_email_decisions_ignore_paired_decoration(wrapper, policy):
    closing = ")" if wrapper == "(" else wrapper
    rules = PrivacyRules.from_config(
        {"student_emails": ["private@x.edu"], "public_emails": ["office@x.edu"]},
        email_policy=policy,
    )
    assert rules.redact(f"{wrapper}private@x.edu{closing}", Counter()) == (
        f"{wrapper}[EMAIL]{closing}"
    )
    assert rules.redact(f"{wrapper}office@x.edu{closing}", Counter()) == (
        f"{wrapper}office@x.edu{closing}"
    )
    assert email_from_text(f"{wrapper}office@x.edu{closing}") == "office@x.edu"


@pytest.mark.parametrize("address", ["o'reilly@x.edu", "user=tag@x.edu", "a/b@x.edu", "*tag@x.edu"])
def test_actual_special_local_parts_are_preserved(address):
    rules = PrivacyRules.from_config({"public_emails": [address]})
    assert rules.redact(address, Counter()) == address


@pytest.mark.parametrize("opening,closing", [("***", "***"), ("**'", "'**")])
def test_nested_email_decoration_preserves_policy_and_wrappers(opening, closing):
    rules = PrivacyRules.from_config({"student_emails": ["private@x.edu"]}, email_policy="legacy")
    assert rules.redact(f"{opening}private@x.edu{closing}", Counter()) == (
        f"{opening}[EMAIL]{closing}"
    )


@pytest.mark.parametrize("name", ["Trần Thị Ý", "Nguyễn Văn A", "Lê Văn Ý"])
@pytest.mark.parametrize("normalization", ["NFC", "NFD"])
def test_contextual_names_allow_single_letter_components(name, normalization):
    text = unicodedata.normalize(normalization, f"Em tên {name}. Hạn nộp 07/11/2026.")
    rules = PrivacyRules()
    rules.learn([], text)
    prepared, _ = normalize_and_redact(text, privacy=rules)
    assert prepared == "Em tên [NAME]. Hạn nộp 07/11/2026."


def test_header_name_with_one_letter_is_learned_but_prose_is_not():
    rules = PrivacyRules()
    rules.learn([("user@gmail.com", "Trần Thị Ý")], "Em là sinh viên năm nhất.\nMục A và B.")
    assert rules.student_names == {"Trần Thị Ý"}
    assert rules.redact("Trần Thị Ý, mục A và B.", Counter()) == "[NAME], mục A và B."


@pytest.mark.parametrize(
    "suffix",
    [
        "/send/user%40gmail.com",
        "/?to=user%2540gmail.com",
        "/?other=user%252540gmail.com",
        "/#to=user%2540gmail.com",
    ],
)
def test_encoded_private_addresses_cannot_survive_in_urls(suffix):
    text, _ = normalize_and_redact("https://example.invalid" + suffix)
    assert "user" not in text and "gmail.com" not in text


@pytest.mark.parametrize("policy", ["all", "legacy"])
def test_url_policy_preserves_public_path_and_other_query_bytes(policy):
    rules = PrivacyRules.from_config({"public_emails": ["office@x.edu"]}, email_policy=policy)
    public = "https://example.invalid/send/office%40x.edu?x=a%26b%3Dc&next=%2Fapply"
    assert rules.redact(public, Counter()) == public
    literal = "https://example.invalid/send/office@x.edu?contact=office@x.edu"
    assert rules.redact(literal, Counter()) == literal
    private = "https://example.invalid/?to=user%2540gmail.com&x=a%26b%3Dc&next=%2Fapply"
    assert rules.redact(private, Counter()) == (
        "https://example.invalid/?to=REDACTED&x=a%26b%3Dc&next=%2Fapply"
    )


def test_plus_in_url_path_is_part_of_address():
    rules = PrivacyRules.from_config({"public_emails": ["office+tag@x.edu"]})
    url = "https://example.invalid/send/office+tag%40x.edu"
    assert rules.redact(url, Counter()) == url


@pytest.mark.parametrize(
    "value", ["user%ZZ%40gmail.com", "user%FF%40gmail.com", "user%" + "25" * 10 + "40gmail.com"]
)
def test_undecodable_url_is_removed_conservatively(value):
    text, _ = normalize_and_redact("https://example.invalid/send/" + value)
    assert "user" not in text


@pytest.mark.parametrize("separator", [".", "/", "-"])
def test_deadline_datetime_is_not_a_phone_number(separator):
    text = f"Hạn nộp 07{separator}11{separator}2026 17:00"
    assert normalize_and_redact(text)[0] == text


@pytest.mark.parametrize("phone", ["0912345678", "+84 912 345 678", "0912.345.678", "0912-345-678"])
def test_supported_phones_remain_private(phone):
    assert normalize_and_redact(f"Liên hệ {phone}.")[0] == "Liên hệ [PHONE]."


@pytest.mark.parametrize(
    "text",
    [
        "Vào trang bài viết:\nHạn nộp 07/11/2026.",
        "Thông báo seminar\nTừ: 8h00\nChủ đề: Học máy\nHạn đăng ký 07/11/2026.",
        "On the course website, see the article wrote:\nDeadline 07/11/2026.",
    ],
)
def test_notice_prose_does_not_become_an_email_attribution(text):
    assert split_thread(text, "")[0].body == text


@pytest.mark.parametrize(
    "html",
    [
        "<blockquote>Hạn nộp: 07/11/2026</blockquote>",
        '<blockquote>Hạn nộp: 07/11/2026<blockquote class="other gmail_quote">'
        "THIRD_PARTY</blockquote>Đăng ký</blockquote>",
    ],
)
def test_plain_blockquotes_preserve_author_text(html):
    text, _, _ = parse_email(_email(html, html=True))
    assert "Hạn nộp: 07/11/2026" in text and "THIRD_PARTY" not in text


def test_html_bottom_reply_survives_removal_of_cited_message():
    text, _, _ = parse_email(
        _email(
            "<p>On Monday, A &lt;a@example.invalid&gt; wrote:</p>"
            '<blockquote type="cite">THIRD_PARTY</blockquote>'
            "<p>Đăng ký trước 07/11/2026.</p>",
            html=True,
        )
    )
    assert text == "Đăng ký trước 07/11/2026."


def test_phone_label_resolves_date_shaped_number_as_private():
    assert "07.11.2026 17" not in normalize_and_redact("SĐT: 07.11.2026 17")[0]


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            "https://example.invalid/?section=2&region=3",
            "https://example.invalid/?section=2&region=3",
        ),
        (
            parse_html('<a href="https://example.invalid/?section=2&amp;region=3">Link</a>'),
            "https://example.invalid/?section=2&region=3",
        ),
        (
            parse_html('<a href="https://example.invalid/?section=2&amp;amp;region=3">Link</a>'),
            "https://example.invalid/?section=2&amp;region=3",
        ),
    ],
)
def test_html_entities_are_decoded_only_at_the_html_boundary(source, expected):
    text, links = extract_links(source, keep_in_text=True)
    assert links == [expected] and expected in text
    assert "§" not in text and "®" not in text


def test_safe_text_attachments_offsets_and_label_studio_export(tmp_path):
    source = tmp_path / "notice.eml"
    source.write_bytes(
        _email(
            "<table><tr><td>Đăng ký <blockquote>Hạn nộp 07.11.2026 17:00</blockquote>"
            '<div class="gmail_quote">THIRD_PARTY</div></td></tr></table>'
            "<p>https://example.invalid/send/user%40gmail.com</p>"
            '<a href="https://example.invalid/?section=2&amp;region=3">Chi tiết</a>',
            html=True,
        )
    )
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(
        manifest,
        [
            {
                "path": source.name,
                "source_type": "email",
                "consent_ref": "synthetic-test",
                "synthetic": True,
            }
        ],
    )
    notice = prepare(manifest, tmp_path / "notices.jsonl")[0]
    task = export_tasks([notice])[0]["data"]
    assert "Hạn nộp 07.11.2026 17:00" in task["text"]
    assert "THIRD_PARTY" not in str(task) and "[[EMAIL_QUOTE_" not in str(task)
    assert "user" not in str(task)
    assert task["attachments"] == ["https://example.invalid/?section=2&region=3"]
    assert all(notice.text[s.start : s.end] == s.text for s in notice.sentences)
    assert notice.raw_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    spans = []
    for span_id, label, value in [("a", "ACTION", "Đăng ký"), ("t", "TIME", "07.11.2026 17:00")]:
        start = notice.text.index(value)
        spans.append(
            {
                "id": span_id,
                "type": "labels",
                "value": {
                    "start": start,
                    "end": start + len(value),
                    "text": value,
                    "labels": [label],
                },
            }
        )
    task_with_labels = {
        "data": task,
        "annotations": [
            {
                "completed_by": 42,
                "result": [
                    *spans,
                    {"type": "relation", "from_id": "a", "to_id": "t", "labels": ["DEADLINE"]},
                ],
            }
        ],
    }
    annotation = import_tasks([task_with_labels], [notice])[0]
    assert all(notice.text[s.start : s.end] == s.text for s in annotation.spans)
    assert annotation.events[0].arguments[0].role == "DEADLINE"


def test_audit_uses_the_same_decorated_and_encoded_addresses(tmp_path):
    source = tmp_path / "notice.eml"
    source.write_bytes(
        _email(
            "*office@x.edu*\nhttps://example.invalid/send/contact%2540x.edu\n"
            "https://example.invalid/?to=second%2540x.edu"
        )
    )
    audit_email_policy([source], tmp_path / "audit")
    with (tmp_path / "audit/allowed_emails.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["email"] for row in csv.DictReader(handle)}
    assert rows == {"office@x.edu", "contact@x.edu", "second@x.edu"}


def test_private_audit_includes_addresses_in_html_quotes(tmp_path):
    source = tmp_path / "notice.eml"
    source.write_bytes(_email('<div class="gmail_quote">office@x.edu</div>', html=True))
    audit_email_policy([source], tmp_path / "audit")
    with (tmp_path / "audit/allowed_emails.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert [row["email"] for row in csv.DictReader(handle)] == ["office@x.edu"]


def test_batch_review_mode_keeps_valid_records_and_reports_empty_contribution(tmp_path):
    (tmp_path / "valid.eml").write_bytes(_email("Nộp hồ sơ trước 07/11/2026."))
    empty = _email('<blockquote type="cite">THIRD_PARTY</blockquote>', html=True)
    (tmp_path / "empty.eml").write_bytes(empty)
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(
        manifest,
        [
            {"path": "empty.eml", "source_type": "email", "consent_ref": "synthetic-test"},
            {"path": "valid.eml", "source_type": "email", "consent_ref": "synthetic-test"},
        ],
    )
    errors = tmp_path / "failures.jsonl"
    notices = prepare(manifest, tmp_path / "notices.jsonl", errors_output=errors)
    assert len(notices) == 1
    failures = read_jsonl(errors)
    assert failures[0]["manifest_line"] == 1
    assert failures[0]["doc_id"] == hashlib.sha256(empty).hexdigest()[:20]
    assert failures[0]["reason"] == "empty_notice_body"
    assert "THIRD_PARTY" not in str(failures)


def test_cli_batch_errors_are_visible_and_return_nonzero(tmp_path, capsys):
    (tmp_path / "valid.eml").write_bytes(_email("Thông báo hợp lệ."))
    (tmp_path / "empty.eml").write_bytes(_email("> THIRD_PARTY"))
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(
        manifest,
        [
            {"path": "valid.eml", "source_type": "email", "consent_ref": "synthetic-test"},
            {"path": "empty.eml", "source_type": "email", "consent_ref": "synthetic-test"},
        ],
    )
    output, errors = tmp_path / "notices.jsonl", tmp_path / "errors.jsonl"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "prepare",
                "--manifest",
                str(manifest),
                "--output",
                str(output),
                "--errors-output",
                str(errors),
            ]
        )
    assert exc.value.code == 1
    assert len(read_jsonl(output)) == 1 and len(read_jsonl(errors)) == 1
    console = capsys.readouterr()
    assert "Prepared 1" in console.out and "Rejected 1" in console.out
    assert "THIRD_PARTY" not in str(console)


@pytest.mark.parametrize("target", ["source", "manifest", "output"])
def test_batch_errors_cannot_replace_inputs_or_notice_output(tmp_path, target):
    source = tmp_path / "notice.eml"
    source.write_bytes(_email("Thông báo hợp lệ."))
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(
        manifest, [{"path": source.name, "source_type": "email", "consent_ref": "synthetic-test"}]
    )
    output = tmp_path / "notices.jsonl"
    errors = {"source": source, "manifest": manifest, "output": output}[target]
    original = source.read_bytes(), manifest.read_bytes()
    with pytest.raises(ValueError, match="distinct"):
        prepare(manifest, output, errors_output=errors)
    assert (source.read_bytes(), manifest.read_bytes()) == original


@pytest.mark.parametrize(
    "text",
    [
        "Danh sách sinh viên24120001: đã nộp",
        "https://example.invalid/bang_diem_24120001.pdf",
    ],
)
def test_student_id_joined_to_a_word_is_masked(text):
    assert "24120001" not in normalize_and_redact(text)[0]
