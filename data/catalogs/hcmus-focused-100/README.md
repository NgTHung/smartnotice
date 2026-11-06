# HCMUS-focused notice dataset

This catalog identifies one 100-notice pilot collected on 2026-11-06: 40 HCMUS, 30 UIT and 30 UEH notices. HCMUS has the largest source share. The collection is a pilot for task and audience annotation, not a labeled training set or the project's complete research corpus.

## Use the included dataset

The repository includes the full prepared text of all 100 notices in `notices.jsonl`; teammates can use it immediately after cloning, without crawling again. This is the `team-contact-redacted-v1` text version, with additional contact-name/phone masking and regenerated sentence offsets. Use this version consistently for annotation.

`snapshot_index.jsonl` maps each document to its institution, title, source URL, original-text hash and shared-text hash. `snapshot_summary.json` records counts and additional masking. Raw source IDs remain unchanged, while shared-text hashes and offsets can differ from the local automatic crawl. Do not reuse annotations from another text version without migration and validation.

## Check the shared files

Run without raw HTML or network access:

```powershell
uv run python tools/check_notice_dataset.py --snapshot-dir data/catalogs/hcmus-focused-100
```

This validates the Notice, TeamSnapshotIndex and TeamSnapshotSummary schemas, all 100 source/hash links, 40/30/30 quotas, text lengths, unique IDs/text hashes, date evidence, regenerated sentences, configured contact patterns and summary totals. `validation.json` records the original local crawl audit before extra contact masking; `snapshot_summary.json` describes the shared text version. A privacy-pattern finding in the original audit does not mean that same contact remains in the shared text.

## Optionally rebuild the original sources

Run from the repository root after the setup in the [README](../../../README.md):

```powershell
uv run python tools/fetch_notice_catalog.py --catalog data/catalogs/hcmus-focused-100/sources.jsonl --run-id team-copy-001
```

The output is local under `data/raw/crawls/team-copy-001/`. `prepared/notices.jsonl` contains normalized, automatically redacted text and sentence offsets. `provenance.jsonl` maps the catalog's original document IDs to fetched IDs. Layout changes can change raw hashes and IDs while preserving text; use that mapping when exchanging annotations. Changed prepared text stops reconstruction. Robots denial, authentication, network errors and missing sources are surfaced without bypassing access policy or replacing a notice silently.

## Understand the files

| File | Purpose |
|---|---|
| `notices.jsonl` | Full text and sentence offsets for all 100 notices, ready for team review and annotation |
| `snapshot_index.jsonl` | Source metadata and original/shared text hashes |
| `snapshot_summary.json` | Shared snapshot counts, masking and pending-review state |
| `sources.jsonl` | Exactly 100 public source URLs, institution/source IDs, selectors, raw/text hashes, lengths and unverified date evidence |
| `validation.json` | Automated counts and checks; human review and annotation remain incomplete |
| `collection.json` | Collection settings and hashes of the source catalog, lockfile and collection code |

`sources.jsonl` is a metadata-only catalog. The accompanying prepared snapshot is shared at the user's explicit request for team use; original HTML, rejected pages and private logs remain local. Additional contact masking does not establish completed human privacy review. Privacy/date/content checks and annotation remain pending; the files do not claim human approval.

## Interpret selection

The [collection protocol](../../../docs/collection.md) owns the source URLs, academic terms, genre exclusions, independent-action requirement, attachment handling, deduplication, request policy and verification procedure. Discovery follows listing order rather than random sampling, does not limit notices to the current year, and does not retrieve PDF/image-only instructions. UEH comes from the scholarship category and therefore overrepresents scholarships. Exact text duplicates are removed; near duplicates and template/update families still need grouping review before train/test allocation.

Dates remain unverified evidence and do not become `reference_date` automatically. The team must review content, privacy and dates, annotate task/argument spans and applicability constraints, and independently double-annotate at least 20% of annotated documents. Reserve the proposal's 40-50 web domain-test documents before model development; this collection does not assign training/test splits.

The proposal targets 200-300 web notices plus 150-250 consented emails. This 100-web-notice pilot supplies part of that work. Software checks do not demonstrate annotation agreement, model accuracy, anonymity or full source coverage. The [dated validation report](../../../reports/crawler-validation-2026-11-06.md) records the observed run and limitations.
