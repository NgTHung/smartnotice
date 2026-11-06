# Data and annotation contract

Annotations need stable evidence so every extracted task can be checked against its source. SmartNotice assigns offsets to normalized, redacted text and uses document IDs to connect raw provenance, annotations, and split assignments.

The Pydantic models in [`src/schemas.py`](../src/schemas.py) define accepted fields. JSON Lines files use UTF-8, one object per line. Unknown schema fields fail validation.

## Trace a document

The raw manifest records a relative `path`, `source_type` (`email` or `web`), `source_ref`, collection time, and optional `reference_date`, `selector`, `group_id`, `domain_holdout`, `synthetic`, and `pii_names`. Email collection requires `consent_ref`. Paths stay beneath the manifest directory. Name lists and consent references remain in private raw storage.

A prepared Notice contains the SHA-256 of the source bytes, a `doc_id` from its first 20 hex characters, source provenance, reference date and origin, redacted `text`, sentences, a hashed group ID, holdout/synthetic flags, and privacy review metadata. Email source references contain the content hash, not a participant address or local filename.

`reference_date` comes from the email Date header or a manually verified web publication date. Collection time is not a substitute. Missing or invalid email dates remain null. Numeric dates without years can borrow the reference year and are marked inferred; relative expressions require annotation review. The date helper does not infer a year rollover.

## Trace a crawler run

`crawl-web` writes a separate run directory; its `raw/manifest.jsonl` uses the existing manifest and Notice formats. Automatic collection leaves web `reference_date=null`. Displayed publication evidence is stored separately for human verification. UTF-8 JSONL writers serialize before replacing their destination through a sibling temporary file; this protects a previous file from a failed replacement, but does not make several files transactional.

| Record/file | Persisted fields and meaning |
|---|---|
| `CrawlCandidate`, `candidates.jsonl` | `url`, `title`, `selection_reason`; unique links in listing order, including title exclusions |
| `CrawlIndex`, `index.jsonl` | `doc_id`, `raw_sha256`, `requested_url`, final `url`, article/listing titles, `institution` (`HCMUS`, `UIT`, or `UEH`), `raw_path`, `snapshot_path`, `selector`, `characters`, and `prepared_text_sha256` |
| Index date evidence | `publication_date_candidate`, `publication_date_display`, `published_time_metadata`, `publication_date_status`, `reference_date`, and `date_review_required` |
| Index review metadata | `privacy_review_required`, `content_review_required`, and `warnings`; automated output leaves all review requirements true |
| `CrawlLog`, `crawl_log.jsonl` | `kind` (`listing`, `detail`, `preparation`), requested/final URLs, `status` (`fetched`, `accepted`, `skipped`, `failed`), `reason`, optional snapshot path, accepted `doc_id`, or `duplicate_of` |
| `CrawlSummary`, `summary.json` | Run ID/source/listing, UTC start/finish times, status/completion, target, candidate budget, `max_pages`, request interval, short-text threshold, holdout flag, discovered/eligible/attempted/accepted counts, unique-text and pending-review counts, outcome counts, and optional error |

All crawler models reject unknown fields. Paths in the index/log resolve relative to the run directory. `raw_sha256` hashes HTTP-decoded HTML bytes; the prepared-text hash covers NFC-normalized, automatically redacted UTF-8 text. `doc_id` retains the existing first-20-hex source-hash rule. Deduplication counts identical prepared text once within a run while preserving other downloaded URL outcomes in the log. Missing detail snapshots for HTTP errors or non-HTML responses are expected.

Publication statuses are `unverified`, `missing`, `invalid`, and `conflict`. A candidate can remain present alongside invalid/conflicting metadata; it is never promoted automatically to `reference_date`. The [collection protocol](collection.md) owns manual review and regeneration.

Run statuses are `running`, `complete`, `partial`, `failed`, and `interrupted`. `complete=true` requires both the target count and successful preparation. It makes no claim about human approvals. A failure can leave selected raw sources without prepared output, or stale counts after a storage/process failure. See the [crawler reference](crawler.md) for the exact failure policy.

## Keep offsets stable

Offsets are zero-based, end-exclusive Python Unicode code point indices. `text[start:end]` must equal the stored sentence or span text. Normalize Unicode to NFC, redact identifiers, and segment before exporting annotation tasks. These offsets refer to the prepared text, not raw MIME bytes or DOM positions. The raw hash and manifest preserve source provenance.

Changes to prepared text invalidate existing annotation offsets. Browser exports must match the canonical text exactly. Check offsets after import, especially for pasted emoji or other non-BMP characters because browser indexing can differ from Python indexing.

## Describe an event

Each annotation contains an anonymized annotator ID, spans, events, and reviewed audience constraints. Span labels are ACTION, TIME, AUDIENCE, CONDITION, CHANNEL, and DOCUMENT. Each event references one ACTION, its argument spans, and at least one evidence sentence. Shared arguments can belong to several events. All linked spans must fit inside selected evidence sentences.

TIME arguments require START, DEADLINE, or EVENT_TIME. They may carry `normalized_date` and `inferred`. Other arguments cannot carry time metadata. An inferred date requires a reference date and a normalized value. A date interval uses separate TIME spans for its endpoints.

Audience constraints contain inclusion lists for cohorts, majors, programs, and statuses, an excluded-status list, and an implicit-audience flag. Inclusion attributes combine with AND, values inside an attribute combine with OR, and separate audience branches combine with OR. Encode common exclusions in every branch. Curators resolve abbreviations to shared codes; the matcher only normalizes case and whitespace. Unrepresented conditions require manual review.

## Derive applicability rows

Synthetic profiles contain a profile ID plus optional cohort, major, program, and status. The rule matcher returns NOT_APPLIES for a known exclusion or mismatch, UNCLEAR for implicit/unspecified audiences or missing required profile attributes, and APPLIES when every explicit requirement matches. Absence of a reviewed constraint produces UNCLEAR.

Pair generation also abstains when an otherwise matching event has a free-form CONDITION. The profile schema cannot resolve that condition. A known audience mismatch remains NOT_APPLIES.

Generated pairs retain `doc_id`, event/profile IDs, original evidence text, profile fields, a label, and rule provenance. They are silver labels derived from annotations, not independent human judgments. Model inputs exclude constraint fields, label provenance, and rule reasons. Assign pair splits by joining document split assignments; never split pairs independently.

## Separate evaluation groups

Source threads and manually assigned template groups merge with exact/near text duplicates. Similarity uses normalized character sequences with the threshold passed to `split`; transitive matches form one group. The seeded allocator targets 70/15/15 by document count but cannot guarantee exact proportions or nonempty small splits.

Any group containing a reserved web notice is removed from the ordinary pool. Its web documents receive `domain_test`; related email receives `excluded`. Persist assignments and review group merges before training. Synthetic flags travel with every notice and derived pair.

University source IDs are `hcmus-student`, `uit-student`, `ueh-student`, and `ueh-training`. The multi-university tool writes the same index and Notice records in combined files; index paths include the source subfolder prefix. Raw manifests remain per source. Its combined summary records target, unique accepted count, institution counts, completion, errors and pending review flags. A complete multi-university run requires 100 distinct prepared-text hashes and no source errors.


## Share a source catalog

`NoticeCatalogEntry` records `doc_id`, `source`, `institution`, public `url`, body `selector`, `raw_sha256`, `prepared_text_sha256`, `characters`, `publication_date_candidate` and `publication_date_status`. Unknown fields are rejected. Hash fields contain 64 lowercase hexadecimal characters, and `doc_id` is the first 20 characters of the raw hash. Article bodies, titles, names, contact data and machine-local paths are absent.

The HCMUS-focused batch requires 40 HCMUS, 30 UIT and 30 UEH records. No source quota is silently reassigned. `complete=true` requires exact source quotas, 100 distinct prepared texts, successful source runs and corpus validation. Metadata export independently reruns validation before replacing a catalog.

Catalog reconstruction writes a new local `raw/manifest.jsonl`, source snapshots, `prepared/notices.jsonl`, `provenance.jsonl` and `summary.json`. Provenance records map `catalog_doc_id` to the fetched `doc_id`, institution, final URL, raw hash, raw-hash-match flag and expected prepared-text hash. Rebuilt raw hashes may differ due to HTML changes; prepared text must match exactly or the reconstruction fails. All human-review requirements remain pending, and no original publication date is automatically promoted to `reference_date`.
