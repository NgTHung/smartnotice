"""Retain source bytes locally and record consent without copying mail headers."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartnotice.io import read_jsonl, write_jsonl


def save_source(raw: bytes, raw_dir: Path, source_type: str, **metadata: Any) -> dict:
    """Save content-addressed bytes and append one manifest entry per source."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    suffix = ".eml" if source_type == "email" else ".html"
    destination = raw_dir / f"{digest}{suffix}"
    if destination.exists() and destination.read_bytes() != raw:
        raise ValueError("Raw content hash collision")
    destination.write_bytes(raw)
    row = {
        "path": destination.name,
        "source_type": source_type,
        "source_ref": f"local:{digest}" if source_type == "email" else metadata.pop("url"),
        "collected_at": datetime.now(UTC).isoformat(),
        "synthetic": False,
        **metadata,
    }
    manifest = raw_dir / "manifest.jsonl"
    rows = read_jsonl(manifest) if manifest.exists() else []
    for existing in rows:
        if existing["path"] == row["path"] and existing["source_ref"] == row["source_ref"]:
            previous = {key: value for key, value in existing.items() if key != "collected_at"}
            incoming = {key: value for key, value in row.items() if key != "collected_at"}
            if previous != incoming:
                raise ValueError("Source metadata conflicts with its existing manifest entry")
            return existing
    write_jsonl(manifest, [*rows, row])
    return row


def collect_email(path: Path, raw_dir: Path, consent_ref: str, group_id: str | None) -> dict:
    """Import an .eml file with a non-identifying consent record reference."""
    if path.suffix.lower() != ".eml":
        raise ValueError("Email input must be an .eml file")
    if not consent_ref.strip():
        raise ValueError("A consent record reference is required")
    return save_source(
        path.read_bytes(), raw_dir, "email", consent_ref=consent_ref, group_id=group_id
    )
