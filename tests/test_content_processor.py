"""Thread/privacy cases adapted from Data Email/test_content_processor.py."""

from collections import Counter

import pytest
from smartnotice.parsers.thread import split_thread
from smartnotice.preprocessing.privacy import PrivacyRules


def test_nested_multiline_thread_attributions():
    text = (
        "Nội dung C\nOn Monday,\nB <b@example.invalid>\nwrote:\n> Nội dung B\n"
        "> Vào Chủ nhật, A <a@example.invalid> đã viết:\n>> Nội dung A"
    )
    parts = split_thread(text, "c@example.invalid")
    assert [(part.sender, part.body) for part in parts] == [
        ("c@example.invalid", "Nội dung C"),
        ("b@example.invalid", "Nội dung B"),
        ("a@example.invalid", "Nội dung A"),
    ]


def test_unattributed_quote_is_not_assigned_to_replier():
    parts = split_thread("Phần mới\n> Tác giả chưa rõ", "b@example.invalid")
    assert parts[0].body == "Phần mới"
    assert parts[1].sender is None and parts[1].kind == "quoted"


@pytest.mark.parametrize(
    "header",
    [
        "From: A <a@example.invalid>\nSent: Monday\nSubject: Thông báo",
        "Từ: A <a@example.invalid>\nĐã gửi: Thứ hai\nChủ đề: Thông báo",
    ],
)
def test_outlook_headers_split_contributions(header):
    parts = split_thread(
        f"Nhắc lại\n________________\n{header}\n\nThông báo gốc", "b@example.invalid"
    )
    assert [part.body for part in parts] == ["Nhắc lại", "Thông báo gốc"]


def test_legacy_decision_order_and_fallback():
    rules = PrivacyRules.from_config(
        {
            "public_emails": ["office@gmail.com"],
            "student_emails": ["office@gmail.com", "24c06@student.hcmus.edu.vn"],
        },
        email_policy="legacy",
    )
    assert rules.email_decision("OFFICE@gmail.com") == (True, "explicit_public")
    assert rules.email_decision("24c06@student.hcmus.edu.vn") == (False, "explicit_private")
    assert rules.email_decision("24clc06@gmail.com") == (True, "group_local_part")
    assert rules.email_decision("tcta_2k24+news@student.hcmus.edu.vn") == (True, "group_local_part")
    assert rules.email_decision("learner@gmail.com") == (False, "personal_domain")
    assert rules.email_decision("learner@student.hcmus.edu.vn") == (False, "student_domain")
    assert rules.email_decision("24129999@example.invalid") == (False, "numeric_local_part")
    assert rules.email_decision("unknown@example.invalid") == (True, "not_matched_private_rule")


def test_default_masks_all_except_explicit_contacts():
    rules = PrivacyRules.from_config({"public_emails": ["office@example.invalid"]})
    assert rules.is_private_email("unknown@example.invalid")
    assert rules.is_private_email("24c06@student.hcmus.edu.vn")
    assert not rules.is_private_email("OFFICE@example.invalid")


def test_private_fields_masked_but_academic_dates_and_class_retained():
    rules = PrivacyRules.from_config({"student_names": ["Nguyễn Văn Mẫu"]})
    text = rules.redact(
        "Nguyễn Văn Mẫu, MSSV: 24129999, lớp sinh hoạt 24C06.\n"
        "SĐT: 0912 345 678. Ngày sinh: 12/03/2006\n"
        "Địa chỉ thường trú: 10 Đường Mẫu\n"
        "Hạn 27/09/2026, ngày 20260927, GPA ≥ 3.2; môn BAA00103.",
        Counter(),
    )
    assert all(
        value not in text
        for value in ["Nguyễn Văn Mẫu", "24129999", "0912", "12/03/2006", "10 Đường Mẫu"]
    )
    assert all(
        value in text for value in ["24C06", "27/09/2026", "20260927", "GPA ≥ 3.2", "BAA00103"]
    )


def test_header_identity_learning_does_not_classify_office_name_as_student():
    rules = PrivacyRules()
    rules.learn(
        [
            ("24129999@student.hcmus.edu.vn", "Nguyễn Văn Mẫu"),
            ("office@example.invalid", "Phòng Đào Tạo"),
        ],
        "",
    )
    assert "Nguyễn Văn Mẫu" in rules.student_names
    assert "Phòng Đào Tạo" not in rules.student_names


def test_wrapped_and_shared_prefix_names():
    rules = PrivacyRules.from_config({"student_names": ["Nguyễn Văn Mẫu", "Nguyễn Văn Mẫu Bình"]})
    assert rules.redact("Nguyễn Văn Mẫu Bình và Nguyễn\nVăn Mẫu", Counter()) == "[NAME] và [NAME]"


@pytest.mark.parametrize(
    "config", [{"unknown": []}, {"public_emails": "address"}, {"student_names": [""]}, []]
)
def test_invalid_configuration_rejected(config):
    with pytest.raises(ValueError):
        PrivacyRules.from_config(config)
