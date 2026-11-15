"""Collect a bounded HCMUS pilot with durable evidence and explicit run outcomes."""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

import httpx
from smartnotice.collectors.hcmus import (
    NoticeRejected,
    discover_links,
    parse_detail,
)
from smartnotice.collectors.local import save_source
from smartnotice.collectors.sources import SOURCES, next_listing
from smartnotice.collectors.web import UnsupportedContentError, WebCollector
from smartnotice.io import write_jsonl
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.text import normalize_and_redact
from smartnotice.schemas import (
    CrawlCandidate,
    CrawlIndex,
    CrawlLog,
    CrawlSummary,
    NoticeCatalogEntry,
    Record,
)


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
    source: str = "hcmus-student",
    max_pages: int = 1,
    max_candidates: int = 40,
    min_chars: int = 100,
    domain_holdout: bool = False,
    group_id: str | None = None,
    exclude_notices: Sequence[NoticeCatalogEntry] = (),
) -> CrawlSummary:
    """Collect unique academic HTML notices into a new, private run directory.

    Try at most max_candidates eligible links across max_pages listing pages.
    source selects a configured university adapter; discovery preserves DOM order.
    exclude_notices skips known URLs and rejects matching prepared text across runs.
    min_chars only flags short text. Dates remain unverified candidates in the
    index and null in the raw manifest. Return complete/partial after preparing
    accepted sources; raise on policy, network, storage or unexpected failures.
    Checkpoint failed/interrupted runs when storage permits. Reusing a directory
    is rejected before HTTP or writes. This synchronous API is single-writer.
    """
    validate_run_id(run_dir.name)
    if limit < 1 or max_candidates < limit or min_chars < 1:
        raise ValueError("Require limit >= 1, max-candidates >= limit, and min-chars >= 1")
    if source not in SOURCES or max_pages < 1:
        raise ValueError("Require a supported source and max-pages >= 1")
    adapter = SOURCES[source]
    listing_url = adapter.listing_url
    run_dir.mkdir(parents=True, exist_ok=False)
    index: list[CrawlIndex] = []
    log: list[CrawlLog] = []
    summary = CrawlSummary(
        run_id=run_dir.name,
        source=source,
        listing_url=listing_url,
        started_at=datetime.now(UTC),
        target=limit,
        max_candidates=max_candidates,
        max_pages=max_pages,
        interval_seconds=collector.interval,
        short_text_threshold=min_chars,
        domain_holdout=domain_holdout,
    )
    kind, active_url, final_url, snapshot = "listing", listing_url, None, None
    known_urls = {notice.url for notice in exclude_notices}
    text_hashes = {notice.prepared_text_sha256: notice.doc_id for notice in exclude_notices}
    try:
        _atomic_text(run_dir / "raw/manifest.jsonl", "")
        _checkpoint(run_dir, summary, index, log)

        def eligible_candidates() -> Iterator[CrawlCandidate]:
            nonlocal kind, active_url, final_url, snapshot
            candidates: list[CrawlCandidate] = []
            seen_urls: set[str] = set()
            visited: set[str] = set()
            page_url: str | None = listing_url
            for page in range(1, max_pages + 1):
                if not page_url or page_url in visited:
                    break
                kind, active_url, final_url, snapshot = "listing", page_url, None, None
                raw, final_url = collector.fetch(page_url, allowed_origin=listing_url)
                visited.add(page_url)
                visited.add(final_url)
                snapshot = _snapshot(run_dir, raw)
                log.append(
                    CrawlLog(
                        kind="listing",
                        requested_url=page_url,
                        url=final_url,
                        status="fetched",
                        reason="listing_fetched",
                        snapshot_path=snapshot,
                    )
                )
                discovered = discover_links(raw, final_url, link_selector=adapter.link_selector)
                fresh = [row for row in discovered if row.url not in seen_urls]
                candidates.extend(fresh)
                seen_urls.update(row.url for row in fresh)
                _records(run_dir / "candidates.jsonl", candidates)
                summary.discovered_links = len(candidates)
                summary.eligible_candidates = sum(
                    r.selection_reason == "eligible" for r in candidates
                )
                _checkpoint(run_dir, summary, index, log)
                if not fresh:
                    break
                # Resolve paging before yielding: detail fetches update the outer URL state.
                following = next_listing(raw, final_url, adapter, page)
                yield from (
                    row
                    for row in fresh
                    if row.selection_reason == "eligible" and row.url not in known_urls
                )
                page_url = following

        for candidate in islice(eligible_candidates(), max_candidates):
            kind, active_url, final_url, snapshot = "detail", candidate.url, None, None
            summary.attempted_details += 1
            try:
                raw, final_url = collector.fetch(active_url, allowed_origin=listing_url)
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
            if final_url in known_urls:
                log.append(
                    CrawlLog(
                        kind="detail",
                        requested_url=active_url,
                        url=final_url,
                        status="skipped",
                        reason="excluded_url",
                        snapshot_path=snapshot,
                    )
                )
                _checkpoint(run_dir, summary, index, log)
                continue
            try:
                detail = parse_detail(
                    raw,
                    body_selector=adapter.body_selector,
                    title_selector=adapter.title_selector,
                    date_selector=adapter.date_selector,
                )
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
                institution=adapter.institution,
                doc_id=raw_digest[:20],
                raw_sha256=raw_digest,
                requested_url=active_url,
                url=final_url,
                title=detail.title,
                listing_title=candidate.title,
                raw_path=f"raw/{raw_digest}.html",
                snapshot_path=snapshot,
                selector=adapter.body_selector,
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
                selector=adapter.body_selector,
                reference_date=None,
                publication_date_candidate=(
                    detail.date_candidate.isoformat() if detail.date_candidate else None
                ),
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
        kind, active_url, final_url, snapshot = "preparation", listing_url, None, None
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
