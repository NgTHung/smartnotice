# Data and annotation contract

Annotations need stable evidence so every extracted task can be checked against its source. SmartNotice assigns offsets to normalized, redacted text and uses document IDs to connect raw provenance, annotations, and split assignments.

The Pydantic models in [`src/schemas.py`](../src/schemas.py) define accepted fields. JSON Lines files use UTF-8, one object per line. Unknown schema fields fail validation.

## Trace a document

The raw manifest records a relative `path`, `source_type` (`email` or `web`), `source_ref`, collection time, and optional `reference_date`, `selector`, `group_id`, `domain_holdout`, `synthetic`, and `pii_names`. Email entries require a nonblank `consent_ref`; `prepare()` stops the batch when one is missing because the manifest is the last consent boundary before text enters the corpus. Paths stay beneath the manifest directory. Name lists and consent references remain in private raw storage.

A prepared Notice contains the SHA-256 of the source bytes, a `doc_id` from its first 20 hex characters, source provenance, reference date and origin, redacted `text`, sentences, a hashed group ID, holdout/synthetic flags, and privacy review metadata. Email source references contain the content hash, not a participant address or local filename.

`attachments` is an ordered list of distinct HTTP(S) or `www.` URLs, not MIME attachment files. URLs remain in `text` as annotation evidence; each stored URL must occur there. The HTML parser decodes entities once; plain-text link extraction unfolds URLs without entity decoding. Preparation filters privacy before copying URLs. Link comparison ignores scheme/host case and preserves path/query case. Missing `attachments` in older records defaults to an empty list.

URL privacy inspection splits components before decoding percent escapes, with at most eight decoding passes and strict UTF-8. Literal `+` means a space only in query components. Redaction and the private audit share this inspection. Private email addresses in query values replace those values with `REDACTED`; other query pairs retain their original encoding. Private addresses in paths, fragments, authority, or query keys replace the whole URL with `[REDACTED_URL]`. Invalid or excessive percent encoding also produces that placeholder, which is excluded from `attachments`. Sensitive query keys remain private even with literal `amp;` prefixes; this check does not decode HTML entities or introduce query separators. The audit records an uninspectable body as a failure by source hash.

`parser_warnings` contains safe MIME/charset warning codes and defaults to an empty list. `email_policy` records `all` (the default) or explicitly selected `legacy`. `privacy_rules_sha256` records the private configuration's source-byte SHA-256, or null when no file was supplied. The learned identity lists, original header fields, and configuration itself are not exported. Privacy learning from headers is local to each source; processing another email cannot change this notice's learned name list.

One raw source still produces one Notice. Email parsing retains the outer author's contribution, including inline/bottom-posted replies, and excludes quoted or forwarded contributions. It does not create separate notices or infer historical dates from recovered quotations. A source with no remaining body fails preparation. Similar documents remain available for group-safe splitting instead of being discarded by the standalone cleaner's sender/content deduplication.

HTML email quotations require a `gmail_quote` class token or a blockquote with `type="cite"`. These regions are removed before table conversion. Ordinary blockquotes retain their text. Literal strings such as `[[EMAIL_QUOTE_START]]` have no control meaning. Plain-text reply boundaries require a sender/date attribution or a consecutive, plausible email-header cluster; notice headings such as `Từ: 8h00` and `Chủ đề:` remain content.

`prepare()` defaults to stopping on a source error before replacing the notice output. Supplying `errors_output`, also exposed as CLI `--errors-output`, enables batch review: valid notices are written and rejected sources produce `PreparationFailure` JSONL. Each failure contains `manifest_line` (one-based entry position), `doc_id`, `raw_sha256`, and `reason` (`empty_notice_body`, `email_parse_failed`, or `web_parse_failed`), without source text or private filenames. The CLI reports both counts and exits nonzero when sources fail. Invalid manifest metadata, path escapes, conflicting duplicate entries, and schema errors stop the batch. Outputs cannot replace the manifest, raw sources, or privacy configuration.

Email policy comparisons normalize NFC and case-fold both local part and domain, including configured addresses. This is the project's comparison policy, not a universal mailbox-equivalence rule. Paired emphasis, quotes, equals signs, and slashes around an address remain outside its replacement span; unpaired special characters remain part of the local part. Names learned from private headers or explicit name introductions may include single-letter components. Outside an explicit name label, a phrase after `sinh viên`, `em là`, or a similar introduction is learned only when it begins with a recognized surname, and generic phrases such as `Khoa Công Nghệ Thông Tin` are never learned. This keeps audience text available to annotators. Listed names of three or more words match across diacritic forms; two-word names require their exact letters because their folded forms collide with ordinary words. Student and staff names receive the same `[NAME]` placeholder. [`names.py`](../src/preprocessing/names.py) masks unlisted names after a title or role, surname-led names after a student-style word or on a student-ID line, full names of three or more words, and two-word surname-led names alone on a line. It leaves listed public names, place context such as `đường` or `học bổng`, and generic headings readable. Unlisted given names without a title and two-word names in running text can remain visible, and a capitalized phrase can be masked in error, so the review step checks both directions. Generic eight-digit student IDs beginning with `1` or `2` are masked even when they parse as dates, unless valid calendar context immediately precedes them. The rule also matches an ID joined to a preceding word or underscore, as in a file name inside a URL, so it can alter an opaque URL token containing such a digit run. Explicit student-ID and birthdate labels remain private. Valid separated calendar dates are protected from the generic mobile-number rule; explicit phone labels take precedence. Automatic filtering always requires human privacy review.

`reference_date` comes from the email Date header or a manually verified web publication date. Collection time is not a substitute. Missing or invalid email dates remain null. Numeric dates without years can borrow the reference year and are marked inferred; relative expressions require annotation review. The date helper does not infer a year rollover.

## Keep offsets stable

Offsets are zero-based, end-exclusive Python Unicode code point indices. `text[start:end]` must equal the stored sentence or span text. Normalize Unicode to NFC, redact identifiers, and segment before exporting annotation tasks. These offsets refer to the prepared text, not raw MIME bytes or DOM positions. The raw hash and manifest preserve source provenance.

Changes to prepared text invalidate existing annotation offsets. Browser exports must match the canonical text exactly. Browser indexing can differ from Python indexing for characters outside the Basic Multilingual Plane (BMP), so normalization removes emoji in that range along with their modifiers and joiners. A space replaces an emoji only between two letters or digits. BMP symbols such as `⚠` remain. Non-emoji BMP-external characters, such as mathematical letters, remain because they can carry words; the `non_bmp_documents` count in `quality` output identifies text that still needs an offset check after import. The raw bytes keep the removed emoji, and removal can leave a space before punctuation. A body containing only such emoji fails as `empty_notice_body`.

Sentences break at line ends and at `.`, `!`, or `?` before whitespace. A period does not end a sentence after a listed title or place abbreviation (`TS`, `ThS`, `PGS`, `GS`, `KS`, `BS`, `TP`, `Tp`, `Mr`, `Mrs`, `Ms`, `Dr`, `P`, `Q`) or after a line-leading list marker such as `1.` or `a.`. Model quotes must fit inside one sentence, so this keeps phrases such as `TP. Hồ Chí Minh` quotable. Changing these rules changes sentence IDs and requires the same revalidation as a text change.

Label Studio task data also carries `attachments` and `privacy_review_required`. Spans and model suggestions continue to resolve exclusively against `text`; the URL list is metadata, not a second offset coordinate system. Changing cleaning rules requires preparing and validating affected annotations again.

## Describe an event

Each annotation contains an anonymized annotator ID, spans, events, and reviewed audience constraints. Span labels are ACTION, TIME, AUDIENCE, CONDITION, CHANNEL, and DOCUMENT. Each event references one ACTION, its argument spans, and at least one evidence sentence. Shared arguments can belong to several events. All linked spans must fit inside selected evidence sentences.

TIME arguments require START, DEADLINE, or EVENT_TIME. They may carry `normalized_date` and `inferred`. Other arguments cannot carry time metadata. An inferred date requires a reference date and a normalized value. A date interval uses separate TIME spans for its endpoints.

Each audience constraint references one AUDIENCE span and has a `scope`: `all_students`, `listed`, `implicit`, or `outside_population`. The population is university learners; institution names do not restrict it.

A `listed` constraint holds inclusion attributes: `degree_levels` (`undergraduate`, `master`, `doctoral`), `cohorts` as integer admission years or inclusive `cohort_min`/`cohort_max` bounds, `majors`, `programs`, and `statuses`. Status values come from `active`, `on_leave`, `suspended`, `defended`, and `graduated`. A constraint uses either the cohort list or the bounds. A `listed` constraint needs at least one inclusion attribute or `unrepresented=true`. An `all_students` constraint has no inclusion attributes. Both scopes may carry `excluded_statuses`. `implicit` and `outside_population` constraints carry no attributes. Validation rejects any other combination.

`unrepresented=true` records a reviewed audience requirement that profiles cannot express, such as a class code or role. Inclusion attributes combine with AND, values inside an attribute combine with OR, and separate audience branches combine with OR. Encode common exclusions in every branch. Curators resolve abbreviations to shared codes and convert years of study to admission years with the procedure in the [annotation protocol](annotation.md); the matcher only normalizes case and whitespace.

## Keep model suggestions and human reviews traceable

The LLM draft schema in `src/labeling/llm.py` contains quoted spans and events. A span specifies `span_id`, label, `sentence_id`, exact text, and an optional zero-based occurrence number. Python resolves the quote inside that sentence to canonical offsets. Missing quotes, ambiguous repeated quotes, invalid links, unsupported roles, duplicate IDs, and unlinked spans fail validation. Each ACTION has exactly one event; arguments may be shared. Empty span/event arrays represent a model prediction of no events, which also needs human checking.

`suggest-labels` writes Label Studio task JSON containing `data`, `data.proposal`, and `predictions`. `ProposalProvenance` in `src/schemas.py` owns the versioned run metadata: provider/model, run ID/time, prompt version/hash, text/source hashes, prediction hash, synthetic flag, temperature, and output-token limit. Predictions are distinct from canonical Annotation JSONL. Failures follow `LabelingFailure` and contain a document ID, provider/model, attempt time, and safe reason. Failed records cannot become review predictions.

Real notices require a `ProviderApproval` JSONL row matching the prepared-text hash, document ID, provider, recorded reviewer/time, privacy clearance, and provider-use permission. The prepared privacy flag does not satisfy this requirement. The same file is the human review ledger: `privacy_cleared` on a row matching the current text hash admits a real notice to `export-tasks`, while provider transfer also needs `provider_use_approved` and the provider's name in `providers`, which can be empty for a privacy-only review. `export-tasks` holds uncleared real notices out of its output and refuses to write when none qualify. An invalid ledger row stops either command. `privacy-review-queue` lists uncleared real notices as `PrivacyReviewItem` JSONL containing the text, its hash, review counts, and a blank `approval` template. That template fails validation until a person completes it. The queue contains prepared text, so keep it private. The [LLM review procedure](llm-labeling.md) owns the approval and provider configuration steps.

`import-reviewed-labels` compares a human Label Studio export with the original prediction task file and current Notice text. Each exported task needs exactly one completed or canceled annotation and an identifiable pseudonymous/numeric reviewer. Successful imports produce canonical annotations plus `ReviewRecord` JSONL rows. Decisions distinguish matching content (`accepted`), valid differences (`edited`), and cancellation (`skipped`). Records bind the source text, original prediction, run ID, and final annotation hash. Skipped tasks produce no annotation. This exchange records assisted review; it does not establish independent human agreement or adjudication.

## Derive applicability rows

Synthetic profiles contain a profile ID plus optional `cohort` (integer admission year), `degree_level`, `major`, `program`, and `status`, using the constraint value sets. The rule matcher evaluates one constraint in this order:

| Case | Label | `rule_reason` |
|---|---|---|
| `scope=implicit` | UNCLEAR | `implicit_audience` |
| `scope=outside_population` | NOT_APPLIES | `outside_population` |
| Profile status is in `excluded_statuses` | NOT_APPLIES | `excluded_status` |
| A known profile attribute fails a `listed` requirement | NOT_APPLIES | `mismatched_<attribute>` |
| A required profile attribute is missing | UNCLEAR | `missing_profile_attribute` |
| `unrepresented=true` | UNCLEAR | `unrepresented_requirement` |
| `scope=all_students` | APPLIES | `all_students` |
| Every `listed` requirement matches | APPLIES | `all_constraints_match` |

A profile without a status matches no exclusion and falls under `missing_profile_attribute` when the constraint lists `excluded_statuses`. The first matching row decides the label. Absence of a reviewed constraint produces UNCLEAR, and an event without an AUDIENCE argument produces UNCLEAR with `no_audience_constraint`.

An explicitly recorded target-population policy may override the missing-AUDIENCE default. `build_pairs(..., assume_all_students_without_audience=True)` and the `build-pairs --assume-all-students-without-audience` CLI flag treat an event with no AUDIENCE argument as addressing all university learners. Such rows use `assumed_all_students_no_audience`, retain `audience_policy=assume_all_students_without_audience` and `audience_default_applied=true`, and contain no invented source span. Other rows from an opted-in run record the same policy with `audience_default_applied=false`. Explicit audience constraints and missing constraint rows are unaffected. Eligibility CONDITION arguments can still change a default APPLIES result to UNCLEAR. The default API and CLI behavior remains UNCLEAR when the flag is absent. These policy fields are label provenance and must be excluded from model inputs.

Pair generation also abstains when an otherwise matching event has a CONDITION argument. CONDITION marks eligibility requirements, which the profile schema cannot resolve. A known audience mismatch remains NOT_APPLIES.

Generated pairs retain `doc_id`, event/profile IDs, original evidence text, profile fields, a label, and rule provenance. `annotation_sha256` hashes the curated annotation row and `profile_set_sha256` hashes the ordered list of profile rows, both as canonical JSON with sorted keys. They are silver labels derived from annotations, not independent human judgments. Model inputs exclude constraint fields, label provenance, and rule reasons. Assign pair splits by joining document split assignments; never split pairs independently.

## Separate evaluation groups

Source threads and manually assigned template groups merge with exact/near text duplicates. Similarity uses normalized character sequences with the threshold passed to `split`; transitive matches form one group. The seeded allocator targets 70/15/15 by document count but cannot guarantee exact proportions or nonempty small splits.

Any group containing a reserved web notice is removed from the ordinary pool. Its web documents receive `domain_test`; related email receives `excluded`. Each assignment records its `seed` and `similarity`. Persist assignments and review group merges before training. Synthetic flags travel with every notice and derived pair.
