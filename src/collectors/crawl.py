"""Collect a bounded HCMUS pilot with durable evidence and explicit run outcomes."""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx
from smartnotice.collectors.hcmus import (
    BODY_SELECTOR,
    LIST_URL,
    NoticeRejected,
    discover_links,
    parse_detail,
)
from smartnotice.collectors.local import save_source
from smartnotice.collectors.web import UnsupportedContentError, WebCollector
from smartnotice.io import write_jsonl
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.text import normalize_and_redact
from smartnotice.schemas import CrawlIndex, CrawlLog, CrawlSummary, Record


def validate_run_id(run_id: str) -> str:
    """Return a portable single-folder identifier or raise ValueError before I/O."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
        raise ValueError("run-id must contain 1-64 ASCII letters, digits, underscores or hyphens")
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9]", run_id, flags=re.I):
        raise ValueError("run-id cannot be a reserved Windows device name")
    return run_id


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _records(path: Path, rows: Sequence[Record]) -> None:
    write_jsonl(path, [row.model_dump(mode="json") for row in rows])


def _snapshot(run_dir: Path, raw: bytes) -> str:
    relative = Path("snapshots") / (hashlib.sha256(raw).hexdigest() + ".html")
    path = run_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(raw)
    return relative.as_posix()


def _checkpoint(
    run_dir: Path, summary: CrawlSummary, index: list[CrawlIndex], log: list[CrawlLog]
) -> None:
    summary.accepted = len(index)
    summary.unique_prepared_texts = len({row.prepared_text_sha256 for row in index})
    summary.missing_reference_dates = sum(row.reference_date is None for row in index)
    summary.privacy_review_required = sum(row.privacy_review_required for row in index)
    summary.date_review_required = sum(row.date_review_required for row in index)
    summary.content_review_required = sum(row.content_review_required for row in index)
    summary.outcome_counts = dict(Counter(row.reason for row in log if row.kind == "detail"))
    _records(run_dir / "index.jsonl", index)
    _records(run_dir / "crawl_log.jsonl", log)
    _atomic_text(
        run_dir / "summary.json", json.dumps(summary.model_dump(mode="json"), indent=2) + "\n"
    )


def crawl_web(
    collector: WebCollector,
    run_dir: Path,
    *,
    limit: int = 10,
    max_candidates: int = 40,
    min_chars: int = 100,
    domain_holdout: bool = False,
    group_id: str | None = None,
) -> CrawlSummary:
    """Collect unique academic HTML notices into a new, private run directory.

    Try at most max_candidates eligible links from one listing, in DOM order.
    min_chars only flags short text. Dates remain unverified candidates in the
    index and null in the raw manifest. Return complete/partial after preparing
    accepted sources; raise on policy, network, storage or unexpected failures.
    Checkpoint failed/interrupted runs when storage permits. Reusing a directory
    is rejected before HTTP or writes. This synchronous API is single-writer.
    """
    validate_run_id(run_dir.name)
    if limit < 1 or max_candidates < limit or min_chars < 1:
        raise ValueError("Require limit >= 1, max-candidates >= limit, and min-chars >= 1")
    run_dir.mkdir(parents=True, exist_ok=False)
    index: list[CrawlIndex] = []
    log: list[CrawlLog] = []
    summary = CrawlSummary(
        run_id=run_dir.name,
        listing_url=LIST_URL,
        started_at=datetime.now(UTC),
        target=limit,
        max_candidates=max_candidates,
        interval_seconds=collector.interval,
        short_text_threshold=min_chars,
        domain_holdout=domain_holdout,
    )
    kind, active_url, final_url, snapshot = "listing", LIST_URL, None, None
    text_hashes: dict[str, str] = {}
    try:
        _atomic_text(run_dir / "raw/manifest.jsonl", "")
        _checkpoint(run_dir, summary, index, log)
        raw, final_url = collector.fetch(LIST_URL, allowed_origin=LIST_URL)
        snapshot = _snapshot(run_dir, raw)
        log.append(
            CrawlLog(
                kind="listing",
                requested_url=LIST_URL,
                url=final_url,
                status="fetched",
                reason="listing_fetched",
                snapshot_path=snapshot,
            )
        )
        candidates = discover_links(raw, final_url)
        _records(run_dir / "candidates.jsonl", candidates)
        summary.discovered_links = len(candidates)
        eligible = [row for row in candidates if row.selection_reason == "eligible"]
        summary.eligible_candidates = len(eligible)
        _checkpoint(run_dir, summary, index, log)
        for candidate in eligible[:max_candidates]:
            kind, active_url, final_url, snapshot = "detail", candidate.url, None, None
            summary.attempted_details += 1
            try:
                raw, final_url = collector.fetch(active_url, allowed_origin=LIST_URL)
            except httpx.HTTPStatusError as exc:
                if exc.request.url.path != "/robots.txt" and exc.response.status_code in {404, 410}:
                    log.append(
                        CrawlLog(
                            kind="detail",
                            requested_url=active_url,
                            url=str(exc.request.url),
                            status="skipped",
                            reason=f"http_{exc.response.status_code}",
                        )
                    )
                    _checkpoint(run_dir, summary, index, log)
                    continue
                raise
            except UnsupportedContentError:
                log.append(
                    CrawlLog(
                        kind="detail",
                        requested_url=active_url,
                        status="skipped",
                        reason="non_html",
                    )
                )
                _checkpoint(run_dir, summary, index, log)
                continue
            snapshot = _snapshot(run_dir, raw)
            try:
                detail = parse_detail(raw)
            except NoticeRejected as exc:
                log.append(
                    CrawlLog(
                        kind="detail",
                        requested_url=active_url,
                        url=final_url,
                        status="skipped",
                        reason=exc.reason,
                        snapshot_path=snapshot,
                    )
                )
                _checkpoint(run_dir, summary, index, log)
                continue
            text, _ = normalize_and_redact(detail.text)
            if not text:
                raise ValueError("Normalization produced an empty notice")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest in text_hashes:
                log.append(
                    CrawlLog(
                        kind="detail",
                        requested_url=active_url,
                        url=final_url,
                        status="skipped",
                        reason="duplicate_text",
                        snapshot_path=snapshot,
                        duplicate_of=text_hashes[digest],
                    )
                )
                _checkpoint(run_dir, summary, index, log)
                continue
            raw_digest = hashlib.sha256(raw).hexdigest()
            warnings = list(detail.warnings)
            if len(text) < min_chars:
                warnings.append("short_text")
            row = CrawlIndex(
                doc_id=raw_digest[:20],
                raw_sha256=raw_digest,
                requested_url=active_url,
                url=final_url,
                title=detail.title,
                listing_title=candidate.title,
                raw_path=f"raw/{raw_digest}.html",
                snapshot_path=snapshot,
                selector=BODY_SELECTOR,
                characters=len(text),
                prepared_text_sha256=digest,
                publication_date_candidate=detail.date_candidate,
                publication_date_display=detail.date_display,
                published_time_metadata=detail.date_metadata,
                publication_date_status=detail.date_status,
                warnings=warnings,
            )
            save_source(
                raw,
                run_dir / "raw",
                "web",
                url=final_url,
                selector=BODY_SELECTOR,
                reference_date=None,
                group_id=group_id,
                domain_holdout=domain_holdout,
            )
            index.append(row)
            text_hashes[digest] = row.doc_id
            log.append(
                CrawlLog(
                    kind="detail",
                    requested_url=active_url,
                    url=final_url,
                    status="accepted",
                    reason="accepted",
                    snapshot_path=snapshot,
                    doc_id=row.doc_id,
                )
            )
            _checkpoint(run_dir, summary, index, log)
            if len(index) == limit:
                break
        kind, active_url, final_url, snapshot = "preparation", LIST_URL, None, None
        notices = prepare(run_dir / "raw/manifest.jsonl", run_dir / "prepared/notices.jsonl")
        if len(notices) != len(index):
            raise ValueError("Prepared notice count differs from the selected index")
        summary.complete = len(index) == limit
        summary.status = "complete" if summary.complete else "partial"
        summary.finished_at = datetime.now(UTC)
        _checkpoint(run_dir, summary, index, log)
        return summary
    except (Exception, KeyboardInterrupt) as exc:
        summary.complete = False
        summary.status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        summary.error = f"{type(exc).__name__}: {exc}"
        summary.finished_at = datetime.now(UTC)
        log.append(
            CrawlLog(
                kind=kind,
                requested_url=active_url,
                url=final_url,
                status="failed",
                reason=summary.error,
                snapshot_path=snapshot,
            )
        )
        try:
            _checkpoint(run_dir, summary, index, log)
        except OSError:
            # Keep the original failure and previously persisted evidence if storage fails.
            pass
        raise
