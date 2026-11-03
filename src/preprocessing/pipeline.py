"""Convert a source manifest into redacted documents with evidence offsets."""

import hashlib
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Literal

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.parsers.email import parse_email_details
from smartnotice.parsers.html import parse_html
from smartnotice.preprocessing.links import extract_links
from smartnotice.preprocessing.privacy import load_privacy_rules
from smartnotice.preprocessing.text import normalize_and_redact, normalize_text, segment_sentences
from smartnotice.schemas import Notice


def prepare(
    manifest: Path,
    output: Path,
    *,
    privacy_rules: Path | None = None,
    email_policy: Literal["all", "legacy"] = "all",
) -> list[Notice]:
    """Parse every manifest entry and write one notice per source-byte hash.

    Manifest paths resolve beneath the manifest directory. Conflicting metadata
    for repeated source bytes raises an error rather than hiding provenance.
    URL copies stay in text and attachments. All records validate before output
    replacement. Legacy email retention is explicit and still requires review.
    """
    notices: dict[str, Notice] = {}
    base_rules, rules_sha256 = load_privacy_rules(privacy_rules, email_policy=email_policy)
    root = manifest.resolve().parent
    for number, row in enumerate(read_jsonl(manifest), 1):
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Manifest line {number}: path leaves the source directory")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        thread = None
        warnings: list[str] = []
        privacy = deepcopy(base_rules)
        if row["source_type"] == "email":
            try:
                parsed = parse_email_details(raw)
            except (ValueError, LookupError, UnicodeError) as exc:
                raise ValueError(
                    f"Manifest line {number}: cannot parse email ({digest[:20]})"
                ) from exc
            text, reference, thread = parsed.text, parsed.reference_date, parsed.thread_key
            warnings = parsed.warnings
            privacy.learn(parsed.identities, text)
            origin = "email_header" if reference else "missing"
        elif row["source_type"] == "web":
            text = parse_html(raw, row.get("selector"))
            reference = (
                date.fromisoformat(row["reference_date"]) if row.get("reference_date") else None
            )
            origin = "published" if reference else "missing"
        else:
            raise ValueError(f"Manifest line {number}: unsupported source_type")
        # Unfold and unescape before redaction so hidden query values are checked.
        text, _ = extract_links(normalize_text(text), keep_in_text=True)
        text, count = normalize_and_redact(text, row.get("pii_names"), privacy=privacy)
        text, attachments = extract_links(text, keep_in_text=True)
        text = normalize_text(text)
        if not text:
            raise ValueError(f"Manifest line {number}: empty notice body")
        group_key = row.get("group_id") or thread or digest
        group_id = hashlib.sha256(str(group_key).encode()).hexdigest()[:20]
        notice = Notice(
            doc_id=digest[:20],
            source_type=row["source_type"],
            source_ref=f"local:{digest}" if row["source_type"] == "email" else row["source_ref"],
            raw_sha256=digest,
            reference_date=reference,
            reference_date_origin=origin,
            text=text,
            attachments=attachments,
            parser_warnings=warnings,
            email_policy=email_policy,
            privacy_rules_sha256=rules_sha256,
            sentences=segment_sentences(text),
            group_id=group_id,
            domain_holdout=row.get("domain_holdout", False),
            synthetic=row.get("synthetic", False),
            redaction_count=count,
        )
        if notice.doc_id in notices and notices[notice.doc_id] != notice:
            raise ValueError(f"Conflicting manifest entries: {notice.doc_id}")
        notices[notice.doc_id] = notice
    result = list(notices.values())
    write_jsonl(output, [notice.model_dump(mode="json") for notice in result])
    return result
