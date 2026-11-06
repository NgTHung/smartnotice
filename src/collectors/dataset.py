"""Verify a collected corpus against immutable sources before sharing its catalog."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from smartnotice.collectors.hcmus import parse_detail
from smartnotice.collectors.local import save_source
from smartnotice.collectors.sources import SOURCES
from smartnotice.collectors.web import WebCollector
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.text import normalize_and_redact, segment_sentences
from smartnotice.schemas import CrawlIndex, CrawlSummary, Notice, NoticeCatalogEntry

SOURCE_IDS = {"HCMUS": "hcmus-student", "UIT": "uit-student", "UEH": "ueh-student"}

_SHARE_PHONE = re.compile(r"(?<!\w)\(?(?:\+84|0)(?:[ .()-]*\d){8,10}\)?(?![ .()-]*\d)")
_UPPER_NAME = "[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼỀẾỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴÝỶỸ]"
_NAME_WORD = _UPPER_NAME + r"[^\W\d_]*"
_CONTACT_NAME = re.compile(
    r"(?<!tiếng )(?<!Tiếng )\b(?i:thầy|cô|anh|chị|ms\.|mr\.)[ \t]+"
    + "("
    + _NAME_WORD
    + r"(?:[ \t]+"
    + _NAME_WORD
    + r"){0,5})(?!\w)"
)
_INLINE_CONTACT = re.compile(
    r"(?i:liên hệ):[ \t]*(" + _NAME_WORD + r"(?:[ \t]+" + _NAME_WORD + r"){0,5})(?!\w)"
)


def redact_team_contacts(text: str) -> tuple[str, int]:
    """Mask phone-like strings and honorific contact names before sharing a snapshot.

    Preserve dates and ordinary phrases such as tiếng Anh. These deterministic
    rules supplement existing masking; they do not complete human privacy review.
    """
    text, count = _SHARE_PHONE.subn("[PHONE]", text)
    for pattern in [_CONTACT_NAME, _INLINE_CONTACT]:

        def replace(match):
            start, end = match.span(1)
            return (
                match.group()[: start - match.start()]
                + "[NAME]"
                + match.group()[end - match.start() :]
            )

        text, added = pattern.subn(replace, text)
        count += added
    return text, count


def _contained_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or unsafe corpus path: {relative}")
    return path


def validate_corpus(root: Path, expected_counts: dict[str, int]) -> dict:
    """Check every record, source hash, parsed text, identity, quota and sentence.

    Raise ValueError on inconsistency. Findings describe automated checks only;
    privacy, publication-date and annotation review are never marked complete.
    """
    index = [CrawlIndex.model_validate(row) for row in read_jsonl(root / "index.jsonl")]
    notices = [Notice.model_validate(row) for row in read_jsonl(root / "prepared/notices.jsonl")]
    by_id = {notice.doc_id: notice for notice in notices}
    if len(by_id) != len(notices) or len(index) != len(notices):
        raise ValueError("Index/prepared records have different counts or repeated identities")
    if len({row.doc_id for row in index}) != len(index):
        raise ValueError("Repeated document identity in index")
    counts = dict(Counter(row.institution for row in index))
    if counts != expected_counts:
        raise ValueError(f"Institution quotas differ: {counts}; expected {expected_counts}")
    hashes: set[str] = set()
    date_status: Counter = Counter()
    warnings: Counter = Counter()
    privacy_findings = []
    thresholds = {}
    for institution, count in expected_counts.items():
        source = SOURCE_IDS[institution]
        # A single-source run uses root itself; a batch prefixes paths by source.
        source_root = root / source if (root / source).is_dir() else root
        summary = CrawlSummary.model_validate_json(
            (source_root / "summary.json").read_text(encoding="utf-8")
        )
        manifest = read_jsonl(source_root / "raw/manifest.jsonl")
        logs = read_jsonl(source_root / "crawl_log.jsonl")
        source_index = [row for row in index if row.institution == institution]
        original_index = read_jsonl(source_root / "index.jsonl")
        if source_root != root:
            for original in original_index:
                for field in ["raw_path", "snapshot_path"]:
                    original[field] = f"{source}/{original[field]}"
        if original_index != [row.model_dump(mode="json") for row in source_index]:
            raise ValueError(f"Combined index differs from the source index: {institution}")
        if (
            not summary.complete
            or summary.status != "complete"
            or summary.error
            or summary.source != source
            or summary.accepted != count
            or summary.target != count
            or summary.finished_at is None
            or len(manifest) != count
        ):
            raise ValueError(f"Source run is incomplete or its quota differs: {institution}")
        accepted_ids = [row["doc_id"] for row in logs if row["status"] == "accepted"]
        if sorted(accepted_ids) != sorted(row.doc_id for row in source_index):
            raise ValueError(f"Accepted log differs from the selected index: {institution}")
        by_url = {row["source_ref"]: row for row in manifest}
        thresholds[institution] = summary.short_text_threshold
        for selected in source_index:
            entry = by_url.get(selected.url)
            if (
                entry is None
                or entry.get("reference_date") is not None
                or entry.get("synthetic")
                or entry.get("source_type") != "web"
                or entry.get("selector") != selected.selector
            ):
                raise ValueError(f"Manifest metadata differs: {selected.doc_id}")
            manifest_raw = _contained_file(source_root / "raw", entry["path"]).read_bytes()
            if hashlib.sha256(manifest_raw).hexdigest() != selected.raw_sha256:
                raise ValueError(f"Manifest source hash differs: {selected.doc_id}")
            notice = by_id[selected.doc_id]
            group_key = entry.get("group_id") or selected.raw_sha256
            if notice.group_id != hashlib.sha256(str(group_key).encode()).hexdigest()[
                :20
            ] or notice.domain_holdout != bool(entry.get("domain_holdout", False)):
                raise ValueError(f"Group/holdout provenance differs: {selected.doc_id}")
    for row in index:
        notice = by_id.get(row.doc_id)
        if notice is None:
            raise ValueError(f"Missing prepared record: {row.doc_id}")
        raw = _contained_file(root, row.raw_path).read_bytes()
        snapshot = _contained_file(root, row.snapshot_path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if raw != snapshot or digest != row.raw_sha256 or digest != notice.raw_sha256:
            raise ValueError(f"Source/snapshot hash mismatch: {row.doc_id}")
        if row.doc_id != digest[:20] or notice.source_ref != row.url or notice.synthetic:
            raise ValueError(f"Source identity/provenance mismatch: {row.doc_id}")
        adapter = SOURCES[SOURCE_IDS[row.institution]]
        if row.selector != adapter.body_selector or WebCollector.origin(
            row.url
        ) != WebCollector.origin(adapter.listing_url):
            raise ValueError(f"Unexpected body selector: {row.doc_id}")
        detail = parse_detail(
            raw,
            body_selector=adapter.body_selector,
            title_selector=adapter.title_selector,
            date_selector=adapter.date_selector,
        )
        text, redactions = normalize_and_redact(detail.text)
        text_digest = hashlib.sha256(notice.text.encode("utf-8")).hexdigest()
        if (
            text != notice.text
            or text_digest != row.prepared_text_sha256
            or len(text) != row.characters
            or redactions != notice.redaction_count
            or row.title != detail.title
        ):
            raise ValueError(f"Prepared text/title differs from its source: {row.doc_id}")
        if text_digest in hashes:
            raise ValueError(f"Repeated prepared text: {row.doc_id}")
        hashes.add(text_digest)
        expected_warnings = list(detail.warnings)
        if len(text) < thresholds[row.institution]:
            expected_warnings.append("short_text")
        if row.warnings != expected_warnings:
            raise ValueError(f"Source warning flags differ: {row.doc_id}")
        if (
            row.publication_date_candidate != detail.date_candidate
            or row.publication_date_status != detail.date_status
            or notice.reference_date is not None
            or row.reference_date is not None
        ):
            raise ValueError(f"Date evidence mismatch or unreviewed reference date: {row.doc_id}")
        if not (
            row.privacy_review_required
            and row.date_review_required
            and row.content_review_required
            and notice.privacy_review_required
        ):
            raise ValueError(f"Human review requirement was cleared: {row.doc_id}")
        if not notice.sentences or "\ufffd" in text:
            raise ValueError(f"Empty segmentation or damaged Unicode: {row.doc_id}")
        for sentence in notice.sentences:
            if text[sentence.start : sentence.end] != sentence.text:
                raise ValueError(f"Invalid sentence offsets: {row.doc_id}")
        # Finding IDs and counts stay local; do not print matched personal content.
        signals = {
            "email": r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
            "phone_like": r"(?<!\d)(?:\+84|0)[ .-]?(?:\d[ .-]?){8,9}(?!\d)",
        }
        found = {key: len(re.findall(pattern, text)) for key, pattern in signals.items()}
        if any(found.values()):
            privacy_findings.append({"doc_id": row.doc_id, **found})
        date_status.update([row.publication_date_status])
        warnings.update(row.warnings)
    return {
        "validated_documents": len(index),
        "institutions": counts,
        "unique_prepared_texts": len(hashes),
        "date_status_counts": dict(date_status),
        "warning_counts": dict(warnings),
        "privacy_pattern_findings": privacy_findings,
        "human_privacy_review_complete": False,
        "human_date_review_complete": False,
        "annotations_present": False,
    }


def export_catalog(root: Path, destination: Path, expected_counts: dict[str, int]) -> dict:
    """Write only source URLs and verification metadata after full local validation.

    No article bodies, contact details or human-review approvals are exported.
    An existing catalog is replaced only after the new corpus passes validation.
    """
    report = validate_corpus(root, expected_counts)
    rows = read_jsonl(root / "index.jsonl")
    fields = [
        "doc_id",
        "institution",
        "url",
        "selector",
        "raw_sha256",
        "prepared_text_sha256",
        "characters",
        "publication_date_candidate",
        "publication_date_status",
    ]
    catalog = [
        {"source": SOURCE_IDS[row["institution"]], **{k: row[k] for k in fields}} for row in rows
    ]
    catalog = [NoticeCatalogEntry.model_validate(row).model_dump(mode="json") for row in catalog]
    write_jsonl(destination / "sources.jsonl", catalog)
    return report


def export_team_snapshot(root: Path, destination: Path) -> dict:
    """Publish 100 prepared notices with extra contact masking and rebuilt offsets.

    Preserve source IDs and original hashes; record separate shared-text hashes.
    Keep human review pending. Validate all input before writing any shared text.
    """
    counts = {"HCMUS": 40, "UIT": 30, "UEH": 30}
    validate_corpus(root, counts)
    index = read_jsonl(root / "index.jsonl")
    original = {
        r["doc_id"]: Notice.model_validate(r) for r in read_jsonl(root / "prepared/notices.jsonl")
    }
    released, released_index = [], []
    total_redactions = 0
    for row in index:
        notice = original[row["doc_id"]]
        text, added = redact_team_contacts(notice.text)
        shared = Notice.model_validate(
            {
                **notice.model_dump(),
                "text": text,
                "sentences": segment_sentences(text),
                "redaction_count": notice.redaction_count + added,
            }
        )
        if _SHARE_PHONE.search(text) or _CONTACT_NAME.search(text) or _INLINE_CONTACT.search(text):
            raise ValueError(f"Contact pattern remains in shared record: {notice.doc_id}")
        released.append(shared.model_dump(mode="json"))
        released_index.append(
            {
                "doc_id": row["doc_id"],
                "institution": row["institution"],
                "title": row["title"],
                "url": row["url"],
                "original_prepared_text_sha256": row["prepared_text_sha256"],
                "prepared_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "characters": len(text),
                "additional_redactions": added,
                "publication_date_candidate": row["publication_date_candidate"],
                "publication_date_status": row["publication_date_status"],
            }
        )
        total_redactions += added
    if len({r["prepared_text_sha256"] for r in released_index}) != 100:
        raise ValueError("Contact redaction created duplicate shared texts")
    summary = {
        "documents": 100,
        "institutions": counts,
        "additional_redactions": total_redactions,
        "human_privacy_review_complete": False,
        "human_date_review_complete": False,
        "annotations_complete": False,
        "text_version": "team-contact-redacted-v1",
        "contact_pattern_scan_passed": True,
    }
    write_jsonl(destination / "notices.jsonl", released)
    write_jsonl(destination / "snapshot_index.jsonl", released_index)
    (destination / "snapshot_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def fetch_catalog(collector: WebCollector, catalog: Path, destination: Path) -> int:
    """Fetch frozen URLs, require matching prepared hashes and preserve ID mappings.

    Validate every configured source/origin/selector before network or directory
    creation. Changed text fails rather than silently replacing the corpus.
    HTML layout changes can change raw hashes and IDs; provenance maps old to new.
    """
    rows = [
        NoticeCatalogEntry.model_validate(row).model_dump(mode="json")
        for row in read_jsonl(catalog)
    ]
    if (
        not rows
        or len({r["url"] for r in rows}) != len(rows)
        or len({r["prepared_text_sha256"] for r in rows}) != len(rows)
    ):
        raise ValueError("The catalog must contain unique, nonempty source URLs")
    for row in rows:
        adapter = SOURCES[row["source"]]
        if (
            row["institution"] != adapter.institution
            or row["selector"] != adapter.body_selector
            or WebCollector.origin(row["url"]) != WebCollector.origin(adapter.listing_url)
        ):
            raise ValueError("Catalog entry differs from its configured source")
        if (
            not all(
                re.fullmatch(r"[a-f0-9]{64}", row[field])
                for field in ["raw_sha256", "prepared_text_sha256"]
            )
            or row["doc_id"] != row["raw_sha256"][:20]
        ):
            raise ValueError("Catalog entry has invalid hashes or identity")
    destination.mkdir(parents=True, exist_ok=False)
    write_jsonl(destination / "raw/manifest.jsonl", [])
    provenance = []
    summary = {
        "complete": False,
        "expected": len(rows),
        "accepted": 0,
        "human_privacy_review_complete": False,
        "error": None,
    }
    try:
        for row in rows:
            adapter = SOURCES[row["source"]]
            raw, final_url = collector.fetch(row["url"], allowed_origin=adapter.listing_url)
            digest = hashlib.sha256(raw).hexdigest()
            snapshots = destination / "snapshots"
            snapshots.mkdir(exist_ok=True)
            (snapshots / f"{digest}.html").write_bytes(raw)
            detail = parse_detail(
                raw,
                body_selector=adapter.body_selector,
                title_selector=adapter.title_selector,
                date_selector=adapter.date_selector,
            )
            text, _ = normalize_and_redact(detail.text)
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["prepared_text_sha256"]:
                raise ValueError(f"Source text changed; do not reuse annotations: {row['doc_id']}")
            save_source(
                raw,
                destination / "raw",
                "web",
                url=final_url,
                selector=adapter.body_selector,
                reference_date=None,
            )
            provenance.append(
                {
                    "catalog_doc_id": row["doc_id"],
                    "doc_id": digest[:20],
                    "institution": row["institution"],
                    "url": final_url,
                    "raw_sha256": digest,
                    "raw_hash_matches_catalog": digest == row["raw_sha256"],
                    "prepared_text_sha256": row["prepared_text_sha256"],
                }
            )
            write_jsonl(destination / "provenance.jsonl", provenance)
        notices = prepare(
            destination / "raw/manifest.jsonl", destination / "prepared/notices.jsonl"
        )
        if len(notices) != len(rows):
            raise ValueError("Rebuilt corpus contains repeated source identities")
        summary.update(complete=True, accepted=len(notices))
    except (Exception, KeyboardInterrupt) as exc:
        summary.update(error=f"{type(exc).__name__}: {exc}", accepted=len(provenance))
        raise
    finally:
        (destination / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return len(notices)
