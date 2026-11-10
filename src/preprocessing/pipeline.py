"""Convert a source manifest into redacted documents with evidence offsets."""

import hashlib
from datetime import date
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.parsers.email import parse_email
from smartnotice.parsers.html import parse_html
from smartnotice.preprocessing.text import normalize_and_redact, segment_sentences
from smartnotice.schemas import Notice


def prepare(manifest: Path, output: Path) -> list[Notice]:
    """Parse every manifest entry and write one notice per source-byte hash.

    Manifest paths resolve beneath the manifest directory. Conflicting metadata
    for repeated source bytes raises an error rather than hiding provenance.
    """
    notices: dict[str, Notice] = {}
    root = manifest.resolve().parent
    for number, row in enumerate(read_jsonl(manifest), 1):
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Manifest line {number}: path leaves the source directory")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        thread = None
        if row["source_type"] == "email":
            text, reference, thread = parse_email(raw)
            origin = "email_header" if reference else "missing"
        elif row["source_type"] == "web":
            text = parse_html(raw, row.get("selector"))
            reference = (
                date.fromisoformat(row["reference_date"]) if row.get("reference_date") else None
            )
            origin = "published" if reference else "missing"
        else:
            raise ValueError(f"Manifest line {number}: unsupported source_type")
        text, count = normalize_and_redact(text, row.get("pii_names"))
        if not text:
            raise ValueError(f"Manifest line {number}: empty notice body")
        group_key = row.get("group_id") or thread or digest
        group_id = hashlib.sha256(str(group_key).encode()).hexdigest()[:20]
        notice = Notice(
            doc_id=digest[:20],
            source_type=row["source_type"],
            source_ref=f"local:{digest}" if row["source_type"] == "email" else row["source_ref"],
            raw_sha256=digest,
            publication_date_candidate=row.get("publication_date_candidate"),
            reference_date=reference,
            reference_date_origin=origin,
            text=text,
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
