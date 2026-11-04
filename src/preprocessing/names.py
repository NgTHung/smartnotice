"""Recognize likely person names in Vietnamese notice prose for privacy masking.

Students and staff are both masked. These rules favor privacy over readability for
full names, keep generic academic phrases and public places readable, and never
establish anonymity; every prepared document still requires human privacy review.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable

from smartnotice.preprocessing.links import WEB_LINK

UPPER = "A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ"
NAME_WORD = "[" + UPPER + r"][^\W\d_]*"

# These surnames rarely begin an ordinary capitalized phrase.
SURNAMES = (
    "Nguyễn Trần Lê Phạm Hoàng Huỳnh Phan Vũ Võ Đặng Bùi Đỗ Hồ Ngô Dương Lý Đinh Trương Lương "
    "Lưu Quách Kiều Doãn Khưu Thạch Trịnh Mạc Phùng Vương Tống Giang Hứa Diệp Nghiêm"
).split()
# These are also ordinary words or places, so they need a middle name or person context.
CONTEXT_SURNAMES = "Văn Hà Mai Cao La Từ Tô Thái Châu Lâm Đào Tạ Tăng Đoàn".split()
ROMANIZED_SURNAMES = "Nguyen Tran Pham Hoang Huynh Bui Truong Duong Dinh Phan".split()

GENERIC_PHRASES = {
    "cao đẳng",
    "cao học",
    "châu á",
    "châu âu",
    "chương trình",
    "công nghệ",
    "đà nẵng",
    "đào tạo",
    "dương lịch",
    "hà lan",
    "hà nội",
    "hồ sơ",
    "khoa công",
    "khoa học",
    "la mã",
    "lâm đồng",
    "lưu ý",
    "lý lịch",
    "lý thuyết",
    "năm học",
    "rịa vũng",
    "thái lan",
    "thông tin",
    "trường đại",
    "tự nhiên",
    "văn bản",
    "văn hóa",
    "văn phòng",
    "việt nam",
}
GENERIC_WORDS = set(
    """ban bạn bộ các câu chị chính chỉ chương chuyên clb có cô công của cử cuối đại đang đào đoàn
    em giáo giảng hai hệ hiệu hóa học hội khác khoa khóa kỹ lạc lớp lý mạng máy mới môn năm ngành
    nghệ nhất nhân phần phó phòng quốc quý rịa sau sĩ sinh tại tất thầy thạc thông tiên tiến tin
    tính toán toàn trình trung trưởng trường tư tế và vật viên viện""".split()
)
# Headings often pair a surname-like first word with these, which rarely occur in names.
NEVER_IN_NAME = set(
    "báo chỉ đẳng đơn giáo học kiện ký lịch luận mức môn ngày nghệ nộp nội phí sơ tạo tháng "
    "thuật thuyết trị trình trợ tuyển".split()
)
PUBLIC_NAMES = {
    "hồ chí minh",
    "hoàng diệu",
    "lê duẩn",
    "lê hồng phong",
    "lê lợi",
    "lý thường kiệt",
    "ngô quyền",
    "nguyễn an ninh",
    "nguyễn đình chiểu",
    "nguyễn du",
    "nguyễn huệ",
    "nguyễn tất thành",
    "nguyễn thị minh khai",
    "nguyễn trãi",
    "nguyễn văn cừ",
    "nguyễn văn linh",
    "phạm ngũ lão",
    "phạm văn đồng",
    "phan đình phùng",
    "phan xích long",
    "trần hưng đạo",
    "trần phú",
    "trần quốc toản",
    "võ thị sáu",
    "võ văn kiệt",
    "võ văn tần",
}
# Fields and contact labels end a name wherever they occur in a capitalized run.
ALWAYS_STOP = set("điện email lớp mã mssv ngành phó sđt trưởng và của tại".split())
# These can also be given names, so they end a name only when more words follow.
ROLE_STOP = set("bộ chương hệ khoa khóa năm phòng trung trường viện".split())

_RUN = NAME_WORD + r"(?:[ \t]+" + NAME_WORD + r"){0,5}"
_LONG_RUN = NAME_WORD + r"(?:[ \t]+" + NAME_WORD + r"){1,5}"
_BEFORE = r"(?<![\w\[])"
_AFTER = r"(?![\w\]])"


def _alternatives(names: Iterable[str]) -> str:
    return "|".join(form for name in names for form in (name, name.upper()))


_ANY_SURNAME = _alternatives([*SURNAMES, *CONTEXT_SURNAMES])
_ANY_SURNAME_RUN = "(?:" + _ANY_SURNAME + r")(?:[ \t]+" + NAME_WORD + r"){1,5}"
_TITLE_NAME = re.compile(
    r"(?P<prefix>(?:(?:\b(?:TS|ThS|Th\.S|PGS|GS|KS|BS|NCS|GV|Mr|Mrs|Ms|Dr)\b\.?"
    r"|(?i:\b(?:thầy|cô|ông|bà|giảng\s+viên|giáo\s+viên)\b))[ \t]*)+)"
    r"(?P<name>" + _RUN + ")" + _AFTER
)
_STUDENT_NAME = re.compile(
    r"(?P<prefix>(?i:\b(?:sv|bạn|em|anh|chị|học\s+viên|sinh\s+viên|nhóm\s+trưởng)\b)[ \t:.-]*)"
    r"(?P<name>" + _ANY_SURNAME_RUN + ")" + _AFTER
)
_LINE_NAME = re.compile(_BEFORE + "(?P<name>" + _ANY_SURNAME_RUN + ")" + _AFTER)
_FULL_NAME = re.compile(
    _BEFORE
    + "(?P<name>(?:(?:"
    + _alternatives(SURNAMES)
    + r")|(?:"
    + _alternatives(CONTEXT_SURNAMES)
    + r")(?=[ \t]+(?:Thị|Văn|THỊ|VĂN)\b))(?:[ \t]+"
    + NAME_WORD
    + r"){1,5})"
    + _AFTER
)
_ROMANIZED_NAME = re.compile(
    _BEFORE
    + "(?P<name>(?:"
    + "|".join(ROMANIZED_SURNAMES)
    + r")(?:[ \t]+[A-Z][a-z]+){2,4})"
    + _AFTER
)
_PLACE_BEFORE = re.compile(
    r"(?i)\b(?:đường|phố|quận|phường|thành\s+phố|tp|trường|thpt|thcs|giải(?:\s+thưởng)?|quỹ"
    r"|học\s+bổng|tòa(?:\s+nhà)?|nhà|hội\s+trường|tỉnh|huyện|ký\s+túc\s+xá|số\s*\d+\w*|đ\.)"
    r"[.,:]?\s*$"
)
_VIETNAMESE_LETTERS = "".join(
    character for character in UPPER.lower() if character.isalpha() and ord(character) > 127
)


def fold_name(name: str) -> str:
    """Return casefolded text without diacritics; `đ` folds to `d`."""
    decomposed = unicodedata.normalize("NFD", name).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").casefold()


_FOLDED_CLASSES = {
    letter: "[" + letter + "".join(c for c in _VIETNAMESE_LETTERS if fold_name(c) == letter) + "]"
    for letter in {fold_name(c) for c in _VIETNAMESE_LETTERS}
}


def is_generic_phrase(name: str) -> bool:
    """Return whether a capitalized phrase reads as an institution, heading, or topic."""
    words = name.casefold().split()
    return (
        " ".join(words[:2]) in GENERIC_PHRASES
        or all(word in GENERIC_WORDS for word in words)
        or any(word in NEVER_IN_NAME for word in words[1:])
    )


def has_surname(name: str) -> bool:
    """Return whether the first word is a recognized Vietnamese surname, in any case."""
    return name.split()[0].casefold() in {s.casefold() for s in [*SURNAMES, *CONTEXT_SURNAMES]}


def trim_name(value: str) -> str:
    """Remove a following field or organization from a capitalized word run.

    A role word such as `Khoa` stays when it ends the run because it is also a
    given name. Exact character spacing inside the retained name is preserved.
    """
    words = list(re.finditer(r"\S+", value))
    keep = next(
        (i for i, word in enumerate(words) if i and word.group().casefold() in ALWAYS_STOP),
        len(words),
    )
    for index in range(1, keep):
        if words[index].group().casefold() in ROLE_STOP and keep - index >= 2:
            keep = index
            break
    return value[: words[keep - 1].end()]


def _is_public(name: str) -> bool:
    words = name.casefold().split()
    return any(
        " ".join(words[start:end]) in PUBLIC_NAMES
        for start in range(len(words))
        for end in range(start + 2, len(words) + 1)
    )


def _outside_links(text: str, replace: Callable[[str], str]) -> str:
    """Apply replace between URLs; URL components have their own privacy inspection."""
    pieces = []
    cursor = 0
    for link in WEB_LINK.finditer(text):
        pieces.extend([replace(text[cursor : link.start()]), link.group()])
        cursor = link.end()
    pieces.append(replace(text[cursor:]))
    return "".join(pieces)


def mask_person_names(text: str, stats: Counter) -> str:
    """Return text with likely student and staff names replaced by `[NAME]`.

    A title or role masks a following capitalized run, including a single given
    name. Student-style words and student-ID lines mask surname-led runs. A
    full name of three or more words needs no context, and neither does a
    two-word name alone on its line. Place context, listed public names, and
    generic phrases stay readable. Multiword names found this way are masked
    throughout the text. Unlisted single given names can remain visible.
    """
    found: set[str] = set()

    def masker(minimum: int = 1, whole_line: bool = False) -> Callable[[re.Match], str]:
        def replace(match: re.Match) -> str:
            raw = match["name"]
            name = trim_name(raw)
            prefix = match.groupdict().get("prefix") or ""
            words = name.split()
            start = match.start("name")
            alone = False
            if whole_line:
                line_start = match.string.rfind("\n", 0, start) + 1
                line_end = match.string.find("\n", start)
                line = match.string[line_start : line_end if line_end >= 0 else None]
                alone = line.strip(" \t-*•,.") == raw
            if (
                is_generic_phrase(name)
                or _is_public(name)
                or (not prefix and _PLACE_BEFORE.search(match.string[max(0, start - 28) : start]))
                or (len(words) < minimum and not alone)
            ):
                return match.group()
            stats["name_redacted"] += 1
            if len(words) >= 2:
                found.add(name)
            return prefix + "[NAME]" + raw[len(name) :]

        return replace

    def mask_lines(piece: str) -> str:
        return "".join(
            _LINE_NAME.sub(masker(), line) if "[STUDENT_ID]" in line else line
            for line in piece.splitlines(keepends=True)
        )

    for replace in (
        lambda piece: _TITLE_NAME.sub(masker(), piece),
        lambda piece: _STUDENT_NAME.sub(masker(), piece),
        mask_lines,
        lambda piece: _FULL_NAME.sub(masker(minimum=3, whole_line=True), piece),
        lambda piece: _ROMANIZED_NAME.sub(masker(minimum=3), piece),
    ):
        text = _outside_links(text, replace)

    for name in sorted(found, key=len, reverse=True):
        pattern = _BEFORE + r"\s+".join(map(re.escape, name.split())) + _AFTER

        def replace_capitalized(match: re.Match) -> str:
            # Case-insensitive matching covers headings, but lowercase is ordinary prose.
            if not all(word[0].isupper() for word in match.group().split()):
                return match.group()
            stats["name_redacted"] += 1
            return "[NAME]"

        def replace_found(piece: str, pattern: str = pattern) -> str:
            return re.sub(pattern, replace_capitalized, piece, flags=re.I)

        text = _outside_links(text, replace_found)
    return text


def compile_name_pattern(names: Iterable[str], *, folded: bool = False) -> re.Pattern | None:
    """Compile listed names into one pattern sharing prefixes, or None when empty.

    Large school recipient lists can contain thousands of students. Whitespace
    inside a name matches any whitespace. With folded, callers pass fold_name
    output and each base letter matches all of its Vietnamese diacritic forms.
    """
    trie: dict = {}
    for name in sorted(names):
        node = trie
        for character in " ".join(name.casefold().split()):
            node = node.setdefault(character, {})
        node[""] = {}
    if not trie:
        return None

    def letter(character: str) -> str:
        if character == " ":
            return r"\s+"
        if folded and character in _FOLDED_CLASSES:
            return _FOLDED_CLASSES[character]
        return re.escape(character)

    def expression(node: dict) -> str:
        branches = [letter(c) + expression(child) for c, child in node.items() if c]
        result = "|".join(branches)
        if len(branches) > 1:
            result = "(?:" + result + ")"
        return "(?:" + result + ")?" if "" in node and branches else result

    return re.compile(r"(?<!\w)" + expression(trie) + r"(?!\w)", re.I)
