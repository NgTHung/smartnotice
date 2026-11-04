"""Check person-name masking and generic-phrase retention on invented notices."""

import pytest
from smartnotice.preprocessing.privacy import PrivacyRules
from smartnotice.preprocessing.text import normalize_and_redact


def clean(text, identities=()):
    rules = PrivacyRules()
    rules.learn(list(identities), text)
    return normalize_and_redact(text, privacy=rules)[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SV Trần Thị Bình nộp đơn.", "SV [NAME] nộp đơn."),
        ("Bạn Trần Thị Bình nộp đơn.", "Bạn [NAME] nộp đơn."),
        ("Em Trần Thị Bình nộp đơn.", "Em [NAME] nộp đơn."),
        ("bạn Mai Thị Bình nộp đơn.", "bạn [NAME] nộp đơn."),
        ("1. Trần Thị Bình 24120001 K24", "1. [NAME] [STUDENT_ID] K24"),
        ("MSSV: 24120001 - Mai Hoa", "MSSV: [STUDENT_ID] - [NAME]"),
    ],
)
def test_student_names_in_context_are_masked(text, expected):
    assert clean(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Liên hệ TS. Trần Thị Bình.", "Liên hệ TS. [NAME]."),
        ("Liên hệ PGS.TS. Trần Văn Bình.", "Liên hệ PGS.TS. [NAME]."),
        ("Liên hệ thầy Trần Văn Bình.", "Liên hệ thầy [NAME]."),
        ("Liên hệ cô Hoa để nhận đơn.", "Liên hệ cô [NAME] để nhận đơn."),
        ("Liên hệ Mr Trần Bình.", "Liên hệ Mr [NAME]."),
        ("Giảng viên Lâm Hoa nhận đơn.", "Giảng viên [NAME] nhận đơn."),
        ("TS. Trần Thị Bình Trưởng Khoa nhận đơn.", "TS. [NAME] Trưởng Khoa nhận đơn."),
        ("TS. Nguyễn Đăng Khoa nhận đơn.", "TS. [NAME] nhận đơn."),
    ],
)
def test_staff_names_after_titles_are_masked(text, expected):
    assert clean(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Trân trọng,\nTrần Thị Bình", "Trân trọng,\n[NAME]"),
        ("Trân trọng,\nTrần Bình", "Trân trọng,\n[NAME]"),
        ("Gặp Trần Thị Bình tại phòng 5.", "Gặp [NAME] tại phòng 5."),
        ("NGUYỄN THỊ BÌNH ký.", "[NAME] ký."),
        ("Nguyen Van Binh ky ten.", "[NAME] ky ten."),
    ],
)
def test_full_names_without_context_are_masked(text, expected):
    assert clean(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Đoàn TNCS Hồ Chí Minh phát động.",
        "Lý luận Chính trị học kỳ 1.",
        "LÝ LUẬN CHÍNH TRỊ",
        "TĂNG MỨC TÀI TRỢ CHO SINH VIÊN.",
    ],
)
def test_headings_starting_like_a_surname_stay_readable(text):
    assert clean(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Đoàn Thị Bình ký.", "[NAME] ký."),
        ("Mai Văn Hoa ký.", "[NAME] ký."),
        ("Bạn Đoàn Minh Bình nộp đơn.", "Bạn [NAME] nộp đơn."),
    ],
)
def test_word_like_surnames_need_a_middle_name_or_context(text, expected):
    assert clean(text) == expected


def test_lowercase_prose_is_not_masked_as_a_found_name():
    assert clean("TS. Trần Bình nhận đơn. Giữ trần bình thản.") == (
        "TS. [NAME] nhận đơn. Giữ trần bình thản."
    )


def test_a_name_found_in_context_is_masked_throughout_the_document():
    assert clean("TS. Trần Bình nhận đơn. Gặp Trần Bình sau.") == (
        "TS. [NAME] nhận đơn. Gặp [NAME] sau."
    )


def test_trailing_organization_stays_outside_a_learned_name():
    assert clean("Sinh viên Nguyễn Văn An Khoa Công nghệ nộp đơn. Nguyễn Văn An đã ký.") == (
        "Sinh viên [NAME] Khoa Công nghệ nộp đơn. [NAME] đã ký."
    )


def test_learned_full_names_match_across_diacritic_forms():
    assert clean("Nguyen Van Mau ky.", [("x@gmail.com", "Nguyễn Văn Mẫu")]) == "[NAME] ky."
    assert clean("Ngân Thu Hà ký.", [("x@gmail.com", "Ngan Thu Ha")]) == "[NAME] ký."


def test_two_word_learned_names_require_their_exact_letters():
    identity = [("x@gmail.com", "An Bui")]
    assert clean("An Bui ký. Ấn bụi.", identity) == "[NAME] ký. Ấn bụi."


@pytest.mark.parametrize(
    "text",
    [
        "Sinh viên Khoa Toán Tin nộp đơn. Khoa Toán Tin nhận đơn.",
        "Sinh viên Chương Trình Tiên Tiến đăng ký.",
        "Sinh viên Trường Đại học Khoa học Tự nhiên nộp đơn.",
        "Em là sinh viên Trường Đại học Khoa học Tự nhiên.",
        "Sinh viên Việt Nam và Trường Đại học Việt Nam.",
        "Sinh viên Khoa Công Nghệ Thông Tin nộp đơn.",
        "Tại 227 Nguyễn Văn Cừ, TP. Hồ Chí Minh.",
        "Thành phố Hồ Chí Minh City Hall.",
        "Đường Trần Văn Bình, quận 5.",
        "Học bổng Trần Văn Bình năm 2026.",
        "Hồ Sơ Đăng Ký Học Bổng",
        "HỒ SƠ ĐĂNG KÝ HỌC BỔNG",
        "Lưu Ý Khi Làm Hồ Sơ",
        "Kính gửi Quý Thầy Cô Và Các Bạn.",
        "TS Khoa Học Máy Tính.",
        "Bà Rịa Vũng Tàu.",
        "Bạn Hà Nội nộp đơn.",
        "https://example.invalid/Tran_Van_Binh",
    ],
)
def test_generic_phrases_and_public_places_stay_readable(text):
    assert clean(text) == text


def test_generic_header_display_name_is_not_learned():
    assert clean(
        "Khoa Công Nghệ Thông Tin nhận đơn.", [("x@gmail.com", "Khoa Công Nghệ Thông Tin")]
    ) == ("Khoa Công Nghệ Thông Tin nhận đơn.")
