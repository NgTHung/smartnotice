# Collect notice sources

The collection manifest preserves how each notice entered the corpus so the team can explain its sources and reproduce preprocessing. Keep source bytes unchanged and document consent before importing participant email.

## Select sources

Use public faculty and academic-office notice pages with Vietnamese academic content. Record the actual page URL, institution, notice-body CSS selector, verified publication date, and any template/update group. Use only voluntarily supplied .eml files and keep consent records outside the repository. The corpus targets belong in the [course requirements](assignment.md).

The [root README](../README.md) owns collection and preparation commands. `collect-web` fetches one supplied URL; `crawl-web` discovers a bounded pilot from the configured HCMUS listing. Run each command with `--help` for options. Both use the collector's robots rules, redirected-destination checks, and per-origin spacing based on the larger of the configured interval, Crawl-delay, and Request-rate. The 5 MiB limit applies to decoded response bodies, including robots.txt. Neither command bypasses authentication or retries denied requests.

Use `--domain-holdout` for reserved web notices and `--group-id` for known templates or update families. Do not select reserved test data after looking at model errors. Review duplicate grouping before freezing split assignments.

## Review the manifest

The explicit collectors write content-addressed files and `data/raw/manifest.jsonl`. A crawler run has its own `raw/manifest.jsonl`. Email references and automatic thread IDs are hashed before entering prepared records. Add `pii_names` privately to a manifest entry when known names need masking. Supply a web `reference_date` only after verifying it on the source page. A missing date remains missing.

Record institution and sampling decisions in the private collection log. The executable manifest fields are defined in the [data contract](interface.md). Do not add unreviewed scraped data to the synthetic example manifest.

## Collect an HCMUS pilot

Select `hcmus-student` for the public [Thông tin dành cho người học](https://hcmus.edu.vn/thong-tin-danh-cho-nguoi-hoc/) listing. Discovery reads one HTML response, preserves DOM order and identifying URL queries, and keeps the exact HTTPS origin. It does not follow pagination, download attachments, run JavaScript, or switch to another faculty website when it lacks articles.

The title filter includes academic terms such as học phần, học phí, học bổng, tốt nghiệp, nghỉ học, and ngoại ngữ. The generic phrase sinh viên does not qualify a title on its own. It excludes titles containing danh sách, kết quả, quy chế, quy định, chúc mừng, or thư mời. The detail page must have exactly one configured title and body, and action-bearing prose beyond attachment introductions. This heuristic can miss valid notices or retain unsuitable ones. Human content review determines research inclusion; the filter does not annotate ACTION or judge extraction quality.

`--limit` sets the target number of unique prepared texts. `--max-candidates` bounds detail requests to eligible titles; excluded titles remain in `candidates.jsonl`. `--min-chars` adds a `short_text` warning and never rejects a document by length. Choose `--domain-holdout` and any `--group-id` before collection. The defaults and working entry command belong in the root README.

Every run requires a new portable `--run-id`. `--output-root` defaults to `data/raw/crawls/`, which Git ignores. If you choose another root, keep real corpus files out of version control yourself. Reusing a run directory, including an empty one, fails before HTTP. Runs are synchronous and single-writer; separate processes do not coordinate request spacing.

| Run file | Review purpose |
|---|---|
| `snapshots/<sha256>.html` | Downloaded listing and detail HTML, including rejected/duplicate details |
| `candidates.jsonl` | Unique eligible/excluded listing links and title decisions |
| `raw/<sha256>.html`, `raw/manifest.jsonl` | Selected sources and the manifest consumed by `prepare` |
| `index.jsonl` | Titles, requested/final URLs, source/text hashes, date evidence, and review flags |
| `crawl_log.jsonl` | Listing/detail/preparation outcomes, rejection reasons, and duplicate provenance |
| `prepared/notices.jsonl` | Redacted text and sentence offsets from selected sources |
| `summary.json` | Run settings, timestamps, counts, and completion/failure state |

Only successful HTML responses have snapshots. HTTP errors, redirects, and non-HTML bodies are not archived. Source bytes are the HTTP-decoded HTML payload; compressed wire bytes are not retained. The immutable hashes cover these stored payloads. Multiple URLs with the same normalized, redacted text count once; their detail outcomes and downloaded snapshots remain in the log. Notices differing in text, including a changed deadline, remain separate. The existing grouped split stage handles near duplicates.

The crawler stores displayed publication dates and publication metadata as unverified evidence in the index. Missing, invalid, and conflicting dates retain explicit statuses. It leaves `reference_date=null` in the raw manifest and prepared notices, even when display and metadata agree. Do not substitute collection time or a deadline for a publication date.

## Review a run before annotation

1. Check `summary.json`. `complete=true` means the target was collected and `prepare` succeeded; it does not mean dates, privacy, or content have received human review.
2. Open each accepted source URL or its saved snapshot alongside its prepared text. Check the title, academic scope, action, audience, complete instructions, Vietnamese diacritics, table context, and absence of navigation or view counters. Check `warnings`, especially attachment-dependent context, merged cells and replacement characters. Replace an unsuitable sample in a new run rather than silently counting it.
3. Compare the displayed publication date against the saved page and publication metadata. Record the reviewer and evidence in controlled storage. Create `manifest-reviewed.jsonl` alongside `raw/manifest.jsonl` so source paths stay valid. Set verified dates in that copy and leave unresolved dates null. Keep the automatic manifest and index as evidence of the collection run.
4. Review names, IDs, contact details, links, and free-form personal data. Add private `pii_names` to the reviewed manifest where needed. Automatic redaction does not complete privacy review.
5. Run the existing `prepare` command with the reviewed manifest and a new reviewed output path. The root README shows preparation and export commands with explicit run paths. Prepared-text changes require offsets and affected annotations to be regenerated. Preserve the automatic output and the review record so later changes are traceable.
6. Keep human approvals in the private collection record. Review flags in the automatic index remain true; editing a JSON flag alone is not evidence of a review.

## Recover from an incomplete run

The [crawler reference](crawler.md) defines outcomes and failure handling. An exhausted listing/budget produces `partial` with exit 2 and prepares the accepted subset, including an empty subset. Policy failures, HTTP errors other than missing detail pages, network errors, excessive bodies, and storage failures stop the run. A failed run may retain selected raw files without a prepared file; inspect its manifest and use `prepare` explicitly after resolving the cause.

Ctrl+C records `interrupted` and exits 130 when storage permits. A forced process kill can leave `running`, and an interrupted file replacement can leave a sibling `.tmp` file. Reports are replaced atomically one file at a time, not as a multi-file transaction. If storage fails, use the last readable report together with the manifest and snapshots; counts can lag a preserved raw source. Preserve that directory and choose a new run ID. There is no automatic resume, retry, or cross-run deduplication.

## Inspect prepared text

Check that MIME decoding preserved Vietnamese characters, quoted replies and signatures were removed, and table header/value lines retained the action/date relationship. Quote stripping handles common boundaries and `>` lines; institution-specific footers and inline forwarding require review. Tables with merged headers can need manual correction.

Automatic privacy filtering masks email addresses, labeled student IDs/phone numbers, and supplied names. Every prepared document retains `privacy_review_required=true`; automated matching does not establish anonymity. Review body names, unlabeled IDs, URLs, and free-form personal details before exporting tasks. Fix privacy defects in the source preparation settings and regenerate offsets before annotation.

## Record evidence

For each collection run, retain the manifest, collection date, source selection method, consent record references, parser decisions, quality output, and split assignment file in controlled storage. Record failed sources and exclusion reasons in the collection log. Share reviewed aggregates and source descriptions rather than participant source files.
