"""Remove mail boilerplate; adapted from the supplied Data Email/clean_emails.py."""

import re

from smartnotice.preprocessing.text import normalize_text

FOOTER = re.compile(
    r"^(?:You received this message because you are subscribed to the Google Groups\b"
    r"|This is a copy of a message posted in\b"
    r"|Lưu ý các thông báo chung của Nhà trường\b"
    r"|Email này chỉ sử dụng để thông tin[,\s])",
    re.IGNORECASE,
)


QUOTE_START = re.compile(
    r"^(?:[-_]{2,}\s*(?:Forwarded message|Original Message|Thư được chuyển tiếp)"
    r"|On .{1,250}wrote:\s*$|Vào .{1,250}(?:đã viết|viết):\s*$"
    r"|From:\s*.+|Từ:\s*.+)",
    re.IGNORECASE,
)


def remove_boilerplate(
    text: str, *, remove_signatures: bool = True, remove_footer: bool = True
) -> str:
    """Remove known mail footers/signatures while retaining subsequent contributions."""

    def unquote(line: str) -> tuple[int, str]:
        prefix = re.match(r"^(?:>\s*)*", line).group()
        return prefix.count(">"), line[len(prefix) :]

    lines = text.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        depth, line = unquote(lines[index])
        signature = (
            remove_signatures
            and bool(
                re.fullmatch(
                    r"(?:--|_{5,}|Trân trọng[,.!]*|Kính thư[,.!]*"
                    r"|Best regards[,.!]*|Regards[,.!]*)",
                    line,
                    re.IGNORECASE,
                )
            )
            and any(kept)
        )
        footer = remove_footer and bool(FOOTER.match(line))
        if signature or footer:
            # Retain forwarded messages after a signature/footer: these can
            # contain the actual notice, its deadline and registration URL.
            index += 1
            while index < len(lines):
                next_depth, next_line = unquote(lines[index])
                if (
                    QUOTE_START.match(next_line)
                    or (not remove_footer and FOOTER.match(next_line))
                    or (next_line and next_depth < depth)
                ):
                    break
                index += 1
            while kept and (
                not unquote(kept[-1])[1] or re.fullmatch(r"[-_=]{3,}", unquote(kept[-1])[1])
            ):
                kept.pop()
            if index < len(lines):
                kept.append("")
            continue
        kept.append(lines[index])
        index += 1
    return normalize_text("\n".join(kept))
