"""Preserve academic text and exact offsets when masking shared contact details."""

import pytest
from smartnotice.collectors.dataset import redact_team_contacts
from smartnotice.preprocessing.text import segment_sentences


@pytest.mark.parametrize("phone", ["0948.548.968", "(028) 7306 1976", "+84 912 345 678"])
def test_team_phone_masking(phone):
    text, count = redact_team_contacts(f"Liên hệ: {phone}; nộp trước 20/11/2026.")
    assert phone not in text and "[PHONE]" in text and count == 1
    assert "20/11/2026" in text


def test_team_contact_names_and_offsets():
    text, count = redact_team_contacts("Cô Người Mẫu (028) 7306 1976. Học môn tiếng Anh văn.")
    assert "Người Mẫu" not in text and "[NAME]" in text and count == 2
    assert "tiếng Anh văn" in text
    for sentence in segment_sentences(text):
        assert text[sentence.start : sentence.end] == sentence.text
    assert redact_team_contacts(text) == (text, 0)


def test_team_contact_inline_name_and_dates():
    text, count = redact_team_contacts("Thông tin liên hệ: Người Mẫu – Email: [EMAIL].")
    assert text == "Thông tin liên hệ: [NAME] – Email: [EMAIL]."
    assert count == 1
    unchanged = "Từ 06/11/2026 đến 20/11/2026, sinh viên khóa 2026 nộp học phí 1.500.000 đồng."
    assert redact_team_contacts(unchanged) == (unchanged, 0)


@pytest.mark.parametrize(
    "text",
    [
        "Tiếng Anh ở trình độ B1.",
        "Chứng chỉ tiếng Anh IELTS.",
        "Tiếng Anh Châu Âu.",
        "Tiếng Anh B1.",
    ],
)
def test_language_requirements_are_not_contact_names(text):
    assert redact_team_contacts(text) == (text, 0)
