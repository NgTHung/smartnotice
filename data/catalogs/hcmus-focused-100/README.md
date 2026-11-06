# HCMUS-focused notice pilot

This catalog identifies one 100-notice pilot collected on 2026-11-06: 40 HCMUS, 30 UIT and 30 UEH notices. HCMUS has the largest source share. The collection is a pilot for task and audience annotation, not a labeled training set or the project's complete research corpus.

## Use the shared sources

Run from the repository root after the setup in the [README](../../../README.md):

```powershell
uv run python tools/fetch_notice_catalog.py --catalog data/catalogs/hcmus-focused-100/sources.jsonl --run-id team-copy-001
```

The output is local under `data/raw/crawls/team-copy-001/`. `prepared/notices.jsonl` contains normalized, automatically redacted text and sentence offsets. `provenance.jsonl` maps the catalog's original document IDs to fetched IDs. Layout changes can change raw hashes and IDs while preserving text; use that mapping when exchanging annotations. Changed prepared text stops reconstruction. Robots denial, authentication, network errors and missing sources are surfaced without bypassing access policy or replacing a notice silently.

## Understand the files

| File | Purpose |
|---|---|
| `sources.jsonl` | Exactly 100 public source URLs, institution/source IDs, selectors, raw/text hashes, lengths and unverified date evidence |
| `validation.json` | Automated counts and checks; human review and annotation remain incomplete |
| `collection.json` | Collection settings and hashes of the source catalog, lockfile and collection code |

The catalog contains no article bodies, names, contact lists, full HTML or machine-local paths. Real text remains outside Git under the project's [privacy rules](../../../AGENTS.md). A public university page and automatic masking do not establish completed human privacy review.

## Interpret selection

The [collection protocol](../../../docs/collection.md) owns the source URLs, academic terms, genre exclusions, independent-action requirement, attachment handling, deduplication, request policy and verification procedure. Discovery follows listing order rather than random sampling, does not limit notices to the current year, and does not retrieve PDF/image-only instructions. UEH comes from the scholarship category and therefore overrepresents scholarships. Exact text duplicates are removed; near duplicates and template/update families still need grouping review before train/test allocation.

Dates remain unverified evidence and do not become `reference_date` automatically. The team must review content, privacy and dates, annotate task/argument spans and applicability constraints, and independently double-annotate at least 20% of annotated documents. Reserve the proposal's 40-50 web domain-test documents before model development; this collection does not assign training/test splits.

The proposal targets 200-300 web notices plus 150-250 consented emails. This 100-web-notice pilot supplies part of that work. Software checks do not demonstrate annotation agreement, model accuracy, anonymity or full source coverage. The [dated validation report](../../../reports/crawler-validation-2026-11-06.md) records the observed run and limitations.
