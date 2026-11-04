"""Filter identifiers; adapted from the supplied Data Email/content_processor.py."""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Literal

from smartnotice.parsers.addresses import find_email_addresses, normalize_email
from smartnotice.preprocessing.links import WEB_LINK
from smartnotice.preprocessing.names import (
    NAME_WORD,
    compile_name_pattern,
    fold_name,
    has_surname,
    is_generic_phrase,
    mask_person_names,
    trim_name,
)
from smartnotice.preprocessing.urls import inspect_url

DEFAULT_STUDENT_DOMAINS = {"student.hcmus.edu.vn", "sv.hcmus.edu.vn", "clc.fitus.edu.vn"}


PERSONAL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "yahoo.com.vn",
    "icloud.com",
}


GROUP_LOCAL = re.compile(r"^(?:\d{2}(?:clc|c)\d{2}|tcta[_-]?2k\d{2})(?:[+].*)?$", re.I)


INTRO_NAME = re.compile(
    r"(?i:(?P<labeled>\b(?:em|tôi|mình)\s+tên(?:\s+là)?\s+"
    r"|\b(?:họ\s+(?:và\s+)?tên|tên\s+sinh\s+viên)\s*[:：]\s*)"
    r"|\b(?:em|tôi|mình)\s+là(?:\s+sinh\s+viên)?\s+"
    r"|\bsinh\s+viên\s*[:：]?\s+)"
    r"(?P<name>" + NAME_WORD + r"(?:[ \t]+" + NAME_WORD + r"){1,6})"
)


STUDENT_ID = re.compile(r"(?<!\d)[12]\d{7}(?![^\W_])")


MOBILE = re.compile(r"(?<![\w/])(?:\+?84[ .()-]*|0)[35789](?:[ .()-]*\d){8}(?!\d)")

CALENDAR_DATE = re.compile(r"(?<!\d)(\d{1,2})([/.-])(\d{1,2})\2(\d{4})(?!\d)")
DATE_CONTEXT = re.compile(
    r"(?i)\b(?:ngày(?:\s+thông\s+báo)?|hạn(?:\s+(?:nộp|chót|đăng\s+ký))?"
    r"|thời\s+gian|deadline|date)\s*[:：]?\s*$"
)


PRIVATE_URL_KEYS = {
    "email",
    "mail",
    "name",
    "fullname",
    "full_name",
    "hoten",
    "ho_ten",
    "student",
    "student_id",
    "studentid",
    "mssv",
    "phone",
    "sdt",
    "dob",
    "birthdate",
    "address",
    "password",
    "pass",
    "token",
    "access_token",
    "auth",
    "otp",
}


@dataclass(repr=False)
class PrivacyRules:
    """Apply configured identifiers and an explicit email retention policy.

    ``all`` masks every address except explicit public_emails. ``legacy``
    reproduces the supplied cleaner's domain/local-part rules, including their broad
    fallback allowance. Neither policy completes human privacy review.
    """

    email_policy: Literal["all", "legacy"] = "all"
    student_names: set[str] = field(default_factory=set)
    student_emails: set[str] = field(default_factory=set)
    student_ids: set[str] = field(default_factory=set)
    student_domains: set[str] = field(default_factory=lambda: set(DEFAULT_STUDENT_DOMAINS))
    public_emails: set[str] = field(default_factory=set)
    _name_pattern: re.Pattern | None = field(default=None, init=False, repr=False)
    _folded_name_pattern: re.Pattern | None = field(default=None, init=False, repr=False)
    _cached_names: frozenset[str] = field(default_factory=frozenset, init=False, repr=False)

    @classmethod
    def from_config(
        cls, config: dict, *, email_policy: Literal["all", "legacy"] = "all"
    ) -> "PrivacyRules":
        """Validate the original five list fields; reject unknown keys or policies."""
        if not isinstance(config, dict):
            raise ValueError("Privacy rules must be a JSON object")
        if email_policy not in {"all", "legacy"}:
            raise ValueError("Email policy must be all or legacy")
        allowed = {
            "student_names",
            "student_emails",
            "student_ids",
            "student_domains",
            "public_emails",
        }
        if set(config) - allowed:
            raise ValueError(
                "Unknown privacy rule keys: " + ", ".join(sorted(set(config) - allowed))
            )
        rules = cls(email_policy=email_policy)
        for key, values in config.items():
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"Privacy rule {key} must be an array of nonempty strings")
            getattr(rules, key).update(
                unicodedata.normalize("NFC", item.strip()) for item in values
            )
        rules.student_emails = {normalize_email(email) for email in rules.student_emails}
        rules.public_emails = {normalize_email(email) for email in rules.public_emails}
        rules.student_domains = {domain.casefold() for domain in rules.student_domains}
        return rules

    def is_private_email(self, address: str) -> bool:
        """Return whether the chosen policy masks an address, ignoring case."""
        return not self.email_decision(address)[0]

    def email_decision(self, address: str) -> tuple[bool, str]:
        """Return (allowed, reason code) in the original rule precedence order."""
        address = normalize_email(address)
        if address in self.public_emails:
            return True, "explicit_public"
        if address in self.student_emails:
            return False, "explicit_private"
        if self.email_policy == "all":
            return False, "all_email_policy"
        local, _, domain = address.rpartition("@")
        if GROUP_LOCAL.fullmatch(local):
            return True, "group_local_part"
        if domain in PERSONAL_DOMAINS:
            return False, "personal_domain"
        if domain in self.student_domains:
            return False, "student_domain"
        if re.search(r"\d{7,12}", local):
            return False, "numeric_local_part"
        return True, "not_matched_private_rule"

    def learn(self, headers: list[tuple[str, str]], text: str) -> None:
        """Add private identities from one source to this local rules instance.

        Never persist these names or addresses. Do not reuse the instance across
        sources unless its changing identity set is intentionally part of a run.
        A generic phrase is never learned. Outside an explicit name label, a body
        phrase must begin with a recognized surname, because the capitalized words
        after `sinh viên` usually name a faculty or program rather than a person.
        """
        identity_rules = replace(self, email_policy="legacy")
        text = unicodedata.normalize("NFC", text)
        for address, display_name in headers:
            if identity_rules.is_private_email(address):
                self.student_emails.add(normalize_email(address))
                name = re.sub(r"[\d()\[\]]", "", display_name).replace(",", " ")
                name = unicodedata.normalize("NFC", " ".join(name.split()))
                if re.fullmatch(
                    NAME_WORD + r"(?:\s+" + NAME_WORD + r"){1,6}", name
                ) and not is_generic_phrase(name):
                    self.student_names.add(name)
        for match in INTRO_NAME.finditer(text):
            name = trim_name(match["name"])
            if (
                len(name.split()) >= 2
                and not is_generic_phrase(name)
                and (match["labeled"] or has_surname(name))
            ):
                self.student_names.add(name)

    def sender_alias(self, address: str, stats: Counter) -> str:
        """Return the legacy pseudonym or allowed address; this is not anonymity."""
        if self.is_private_email(address):
            stats["sender_redacted"] += 1
            digest = hashlib.sha256(address.casefold().encode("utf-8")).hexdigest()[:16]
            return f"student_{digest}@redacted.invalid"
        return address

    def redact(self, text: str, stats: Counter) -> str:
        """Return NFC text with identifiers and sensitive URL values masked.

        Count replacements in stats. Only explicit calendar context protects
        compact dates from the generic eight-digit ID rule; labeled IDs and
        birthdates remain private. URL inspection shares the audit's bounded
        component decoding. Unsafe/private path or fragment URLs become
        [REDACTED_URL]. Listed names of three or more words match across diacritic
        forms; `mask_person_names` covers unlisted student and staff names. Names
        outside its rules still require human review.
        """
        text = unicodedata.normalize("NFC", text)

        def replace_url(match: re.Match) -> str:
            raw = match.group()
            try:
                inspected = inspect_url(raw)
                if any(self.is_private_email(address) for address in inspected.outside_query):
                    stats["url_redacted"] += 1
                    return "[REDACTED_URL]"
                pairs = []
                changed = False
                for pair in inspected.query:
                    if any(
                        self.is_private_email(email.address)
                        for email in find_email_addresses(pair.key)
                    ):
                        stats["url_redacted"] += 1
                        return "[REDACTED_URL]"
                    private_value = any(
                        self.is_private_email(email.address)
                        for email in find_email_addresses(pair.value)
                    )
                    key = pair.key.casefold()
                    # Nested literal HTML escapes are not decoded into delimiters,
                    # but cannot conceal a sensitive query key from privacy review.
                    while key.startswith("amp;"):
                        key = key.removeprefix("amp;")
                    if (key in PRIVATE_URL_KEYS or private_value) and pair.value != "REDACTED":
                        pairs.append(pair.raw.partition("=")[0] + "=REDACTED")
                        stats["url_parameter_redacted"] += 1
                        changed = True
                    else:
                        pairs.append(pair.raw)
                # Preserve public URLs byte-for-byte when no private key occurs.
                if not changed:
                    return raw
                before_fragment, separator, fragment = raw.partition("#")
                return (
                    before_fragment.partition("?")[0] + "?" + "&".join(pairs) + separator + fragment
                )
            except ValueError:
                stats["url_redacted"] += 1
                return "[REDACTED_URL]"

        text = WEB_LINK.sub(replace_url, text)

        def mask_addresses(value: str) -> str:
            for email in reversed(find_email_addresses(value)):
                if self.is_private_email(email.address):
                    value = value[: email.start] + "[EMAIL]" + value[email.end :]
                    stats["email_redacted"] += 1
            return value

        # URL components already received their policy decision. Scanning raw
        # URLs as prose would include path/query prefixes in email local parts.
        pieces = []
        cursor = 0
        for link in WEB_LINK.finditer(text):
            pieces.extend([mask_addresses(text[cursor : link.start()]), link.group()])
            cursor = link.end()
        pieces.append(mask_addresses(text[cursor:]))
        text = "".join(pieces)
        names = frozenset(self.student_names)
        if names != self._cached_names:
            self._name_pattern = compile_name_pattern(names)
            # Two-word folded forms collide with ordinary words such as "ấn bụi".
            self._folded_name_pattern = compile_name_pattern(
                {fold_name(name) for name in names if len(name.split()) >= 3}, folded=True
            )
            self._cached_names = names
        for pattern in (self._name_pattern, self._folded_name_pattern):
            if pattern:
                text, count = pattern.subn("[NAME]", text)
                stats["name_redacted"] += count
        for identifier in sorted(self.student_ids, key=len, reverse=True):
            text, count = re.subn(
                r"(?<!\w)" + re.escape(identifier) + r"(?!\w)", "[STUDENT_ID]", text
            )
            stats["student_id_redacted"] += count

        def replace_id(match: re.Match) -> str:
            value = match.group()
            try:
                parsed = date(int(value[:4]), int(value[4:6]), int(value[6:]))
                if 1900 <= parsed.year <= 2100 and DATE_CONTEXT.search(
                    match.string[max(0, match.start() - 50) : match.start()]
                ):
                    return value
            except ValueError:
                pass
            stats["student_id_redacted"] += 1
            return "[STUDENT_ID]"

        # Phone numbers first, so their 8-digit suffix is not mistaken for MSSV.
        # Preserve SmartNotice's established placeholders and labeled-span boundaries.
        text, count = re.subn(
            r"(?i)(\b(?:MSSV|mã\s+(?:số\s+)?sinh\s+viên|student\s+ID)\s*[:#：-]?\s*)\d{6,12}\b",
            lambda match: match[1] + "[STUDENT_ID]",
            text,
        )
        stats["student_id_redacted"] += count
        text, count = re.subn(
            r"(?i)\b(?:điện thoại|sđt|tel|phone)\s*[:.]?\s*\+?\d[\d .()-]{7,}\d",
            "[PHONE]",
            text,
        )
        stats["phone_redacted"] += count

        def replace_phone(match: re.Match) -> str:
            for candidate in CALENDAR_DATE.finditer(match.string):
                if candidate.start() < match.end() and candidate.end() > match.start():
                    try:
                        date(int(candidate[4]), int(candidate[3]), int(candidate[1]))
                    except ValueError:
                        continue
                    return match.group()
            stats["phone_redacted"] += 1
            return "[PHONE]"

        text = MOBILE.sub(replace_phone, text)
        fields = (
            (
                r"(?i)(\b(?:ngày\s+sinh|date\s+of\s+birth|DOB)\s*[:：]\s*)(?:\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}|\d{8})",
                "birthdate_redacted",
                "[NGAY_SINH]",
            ),
            (
                r"(?i)(\b(?:CCCD|CMND|số\s+hộ\s+chiếu|số\s+tài\s+khoản|STK)"
                r"\s*[:：]?\s*)\d[\d .-]{5,20}",
                "identity_number_redacted",
                "[SO_GIAY_TO_TAI_KHOAN]",
            ),
            (
                r"(?im)(\b(?:địa\s+chỉ\s+(?:thường\s+trú|tạm\s+trú|nhà\s+riêng)"
                r"|nơi\s+(?:ở|cư\s+trú))\s*[:：]\s*)[^\n]+",
                "address_redacted",
                "[DIA_CHI_CA_NHAN]",
            ),
            (
                r"(?i)(\b(?:mật\s+khẩu|password|pass|OTP)\s*[:：]\s*)(?!\[)[A-Za-z0-9!@#$%^&*._-]{4,}\b",
                "credential_redacted",
                "[THONG_TIN_DANG_NHAP]",
            ),
        )
        for pattern, key, replacement in fields:
            text, count = re.subn(pattern, lambda match, value=replacement: match[1] + value, text)
            stats[key] += count
        # Runs last so a line's [STUDENT_ID] placeholder can identify its name.
        return mask_person_names(STUDENT_ID.sub(replace_id, text), stats)


def load_privacy_rules(
    path: Path | None = None, *, email_policy: Literal["all", "legacy"] = "all"
) -> tuple[PrivacyRules, str | None]:
    """Load private UTF-8/BOM JSON and return its raw SHA-256, or defaults/None.

    Reject malformed/unknown fields before processing sources. The caller must
    keep the configuration itself private; its digest may be persisted.
    """
    if path is None:
        return PrivacyRules.from_config({}, email_policy=email_policy), None
    raw = path.read_bytes()
    try:
        config = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Privacy rules must be valid UTF-8 JSON") from exc
    return PrivacyRules.from_config(config, email_policy=email_policy), hashlib.sha256(
        raw
    ).hexdigest()
