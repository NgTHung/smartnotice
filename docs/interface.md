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

Audience constraints contain inclusion lists for cohorts, majors, programs, and statuses, an excluded-status list, and an implicit-audience flag. Inclusion attributes combine with AND, values inside an attribute combine with OR, and separate audience branches combine with OR. Encode common exclusions in every branch. Curators resolve abbreviations to shared codes; the matcher only normalizes case and whitespace. Unrepresented conditions require manual review.

## Keep model suggestions and human reviews traceable

The LLM draft schema in `src/labeling/llm.py` contains quoted spans and events. A span specifies `span_id`, label, `sentence_id`, exact text, and an optional zero-based occurrence number. Python resolves the quote inside that sentence to canonical offsets. Missing quotes, ambiguous repeated quotes, invalid links, unsupported roles, duplicate IDs, and unlinked spans fail validation. Each ACTION has exactly one event; arguments may be shared. Empty span/event arrays represent a model prediction of no events, which also needs human checking.

`suggest-labels` writes Label Studio task JSON containing `data`, `data.proposal`, and `predictions`. `ProposalProvenance` in `src/schemas.py` owns the versioned run metadata: provider/model, run ID/time, prompt version/hash, text/source hashes, prediction hash, synthetic flag, temperature, and output-token limit. Predictions are distinct from canonical Annotation JSONL. Failures follow `LabelingFailure` and contain a document ID, provider/model, attempt time, and safe reason. Failed records cannot become review predictions.

Real notices require a `ProviderApproval` JSONL row matching the prepared-text hash, document ID, provider, recorded reviewer/time, privacy clearance, and provider-use permission. The prepared privacy flag does not satisfy this requirement. The same file is the human review ledger: `privacy_cleared` on a row matching the current text hash admits a real notice to `export-tasks`, while provider transfer also needs `provider_use_approved` and the provider's name in `providers`, which can be empty for a privacy-only review. `export-tasks` holds uncleared real notices out of its output and refuses to write when none qualify. An invalid ledger row stops either command. `privacy-review-queue` lists uncleared real notices as `PrivacyReviewItem` JSONL containing the text, its hash, review counts, and a blank `approval` template. That template fails validation until a person completes it. The queue contains prepared text, so keep it private. The [LLM review procedure](llm-labeling.md) owns the approval and provider configuration steps.

`import-reviewed-labels` compares a human Label Studio export with the original prediction task file and current Notice text. Each exported task needs exactly one completed or canceled annotation and an identifiable pseudonymous/numeric reviewer. Successful imports produce canonical annotations plus `ReviewRecord` JSONL rows. Decisions distinguish matching content (`accepted`), valid differences (`edited`), and cancellation (`skipped`). Records bind the source text, original prediction, run ID, and final annotation hash. Skipped tasks produce no annotation. This exchange records assisted review; it does not establish independent human agreement or adjudication.

## Derive applicability rows

Synthetic profiles contain a profile ID plus optional cohort, major, program, and status. The rule matcher returns NOT_APPLIES for a known exclusion or mismatch, UNCLEAR for implicit/unspecified audiences or missing required profile attributes, and APPLIES when every explicit requirement matches. Absence of a reviewed constraint produces UNCLEAR.

Pair generation also abstains when an otherwise matching event has a free-form CONDITION. The profile schema cannot resolve that condition. A known audience mismatch remains NOT_APPLIES.

Generated pairs retain `doc_id`, event/profile IDs, original evidence text, profile fields, a label, and rule provenance. They are silver labels derived from annotations, not independent human judgments. Model inputs exclude constraint fields, label provenance, and rule reasons. Assign pair splits by joining document split assignments; never split pairs independently.

## Separate evaluation groups

Source threads and manually assigned template groups merge with exact/near text duplicates. Similarity uses normalized character sequences with the threshold passed to `split`; transitive matches form one group. The seeded allocator targets 70/15/15 by document count but cannot guarantee exact proportions or nonempty small splits.

Any group containing a reserved web notice is removed from the ordinary pool. Its web documents receive `domain_test`; related email receives `excluded`. Each assignment records its `seed` and `similarity`. Persist assignments and review group merges before training. Synthetic flags travel with every notice and derived pair.

## Exchange event grouping proposals

`import_prediction_tasks` in `src/labeling/studio.py` validates saved prediction tasks against Notice text, source/text/prediction hashes and unique document IDs. It accepts one prediction per task and rejects human completions, unsupported results and unlinked spans. Returned Annotation objects have `annotator_id="model_prediction"`; conversion creates no human review record. `annotation_results` serializes an already validated Annotation into Label Studio spans and relations without assigning authorship or review status.

`group_events` in `src/labeling/grouping.py` accepts unique Notice records and at most one validated Annotation per document. Its Pydantic records define a separate proposal format:

| Record | Fields and guarantees |
|---|---|
| `GroupingConfig` | Token Jaccard candidate threshold in `(0, 1]`, default `0.8`; minimum shared informative tokens, default `3` |
| `EventMention` | `doc_id:action_span_id` reference, document-local event ID, annotation origin, source/text hashes, exact ACTION, arguments, argument spans and evidence sentences |
| `PairDecision` | Member references, Jaccard similarity, decision, rule reasons and whether both members reached the same tentative group |
| `EventGroup` | Hash of sorted member references, member references and `review_required=true`; singleton groups are retained |
| `GroupingResult` | Rule version, config, mentions, groups, candidate decisions and total pair comparison count |

Decisions are `SAME_EVENT`, `DIFFERENT_EVENT`, `UNCLEAR` or `UPDATE_CANDIDATE`. Updates require target/direction review and do not merge automatically. Similarity is a text-overlap score, not a probability. Noncandidate pairs are omitted from decisions; their omission is not a reviewed negative label. Input order does not change the result. Group IDs change when membership changes; they are not permanent external event identifiers.

`tools/run_event_grouping.py` requires matching Notice and prediction document sets and validates them before creating a new output directory. It writes `events.jsonl`, `groups.jsonl`, `pair_decisions.jsonl`, `review_groups.md`, `run.json` and `checksums.json` under private generated storage. Source predictions, text, offsets and evaluation split assignments remain unchanged. Run metadata records parameters, source/code/lock hashes, environment, timings and workflow counts. The [grouping procedure](event-grouping.md) owns decision rules and limitations.

The local `hien.json` sample follows the supplied Label Studio export's task/annotation/result layout, including `entities`/`notice` bindings and ACTION-to-argument relations. Its AI annotations have `completed_by=null`, `ground_truth=false`, `data.draft_origin="ai_assistant_source_reading"` and explicit AI origin in `meta`; no Label Studio user/project identity or human completion is asserted. This file is an assistant draft for further review. It does not satisfy the `import-reviewed-labels` human-review contract. A sidecar preserves canonical AI annotations, the seeded document selection, curation notes and source hashes.

## Assemble event groups and tasks

`build_event_groups` in [`event_groups.py`](../src/labeling/event_groups.py) accepts Notice records, validated Annotations, attributed `GroupingReview` records and optional `TimeBoundaryReview` records. It assembles supplied decisions; it does not classify unreviewed pairs. The models live in [`schemas.py`](../src/schemas.py), reject unknown fields and serialize as UTF-8 JSON. This format is separate from prototype proposals and from the Label Studio human review ledger.

| Record | Contract |
|---|---|
| `MentionVersion` | `doc_id:action_span_id`, raw/text hashes and canonical annotation hash; all must match the supplied input |
| `EvidenceQuote` | Exact prepared-text substring with document, sentence and end-exclusive Python offsets; must fit one source sentence |
| `ReviewAuthor` | Explicit `reviewer_kind` (`ai_assistant` or `human`), nonblank reviewer ID and timezone-aware time; the reserved ID `ai_assistant` cannot use the human kind. Human attribution requires an actual human review supplied by the caller. |
| `GroupingReview` | Unique review ID and unordered pair; four decision labels, task relation, notice relation, rationale, evidence covering both source documents and directed changes for updates |
| `GroupingChange` | One field, optional old source quote and required new quote; new comes from the left/update source, old from the right/previous source |
| `TimeBoundaryReview` | Versioned TIME span, `START`, `END` or `POINT`, author and rationale; optional `value_key` explicitly identifies evidence of the same temporal value |
| `EventGroupAssembly` | Version `event-groups-v1`, complete input mentions, reviews, time interpretations, provisional groups, update applications and conflicts |

`annotation_sha256` hashes the Annotation's `model_dump(mode="json")` encoded as UTF-8 JSON with sorted keys, `ensure_ascii=false` and Python's default separators. A filtered annotation subset has its own hash. Changing spans, authorship, dates or evidence invalidates the corresponding review snapshots. Input records are not mutated. Duplicate documents, duplicate ACTION references, unknown versions, broken evidence and cyclic update directions raise `ValueError` before output is created.

Task relations are `SAME_TASK`, `DIFFERENT_TASK`, `DIFFERENT_SESSION`, `CONDITIONAL_TASK` or `UNRESOLVED`. A `SAME_EVENT` identity edge can therefore retain separate tasks or sessions. `UPDATE_OF` requires `SAME_TASK` and at least one field change; negative/unclear group decisions require `UNRESOLVED` and have no changes. Notice relations (`REMINDER`, `REPEATED_NOTICE`, `UPDATE`, `OTHER`) describe the source communication and do not change task identity.

Positive identity edges form provisional components. An explicit `DIFFERENT_EVENT` or `UNCLEAR` inside such a component produces `group_contradiction` and keeps all its members in singleton groups. Task-equivalence edges have the same consistency check against distinct-task/session/conditional decisions; a `task_contradiction` retains the event group but separates those tasks. Missing cross-pairs supply no reviewed evidence. Every group has `review_required=true` and `privacy_review_required=true`, including groups assembled from human-attributed input. This builder does not finalize approvals or change evaluation split assignments.

Each group retains member references, source document IDs and separate tasks. Each task retains all source facts, `active_values` references and explicit `superseded_by` links. IDs are hashes of sorted membership or versioned evidence and change with membership/snapshot changes; they are not permanent external event IDs. Audience and condition facts remain source-specific, without inferring a common audience or resolving applicability.

Grouping fields are `START`, `END`, `DEADLINE`, `EVENT_TIME`, `AUDIENCE`, `CONDITION`, `CHANNEL`, `DOCUMENT`, `LOCATION` and `STATUS`. END is a grouping interpretation of a reviewed TIME endpoint; Annotation's TIME roles remain START, DEADLINE and EVENT_TIME. LOCATION and STATUS changes carry source quotes without inventing new Annotation span labels. Unrepresented locations may remain in source evidence. Full time phrases preserve qualifiers such as “trước” and “đến hết”; a date and hour in the same phrase need not be split into separate deadlines.

Updates point from new to old, apply only within a consistent shared task, and preserve old/new evidence. TIME updates must resolve to an annotated TIME of the corresponding field, accounting for boundary reviews. A null old quote remains unknown. Identical repeated old values in the task are also superseded, except when an explicit update path identifies them as a newer version. Equivalence uses case-folded, whitespace-normalized quote text, or an explicitly reviewed `value_key`; no date parsing or send-time ordering supplies equivalence. A return to an earlier value follows update direction rather than suppressing the returned value as an old reminder.

Different terminal values for a time, location or status field produce `competing_values`; the builder retains them instead of choosing the latest deadline. Complementary hour/date spans can share a reviewed temporal `value_key` while preserving every quote and offset. Keys have meaning only within the task and field; recording one is a semantic review action, not automatic normalization. Unapplied updates remain recorded when contradictory identity/task decisions prevent a safe merge.

The [grouping procedure](event-grouping.md#dựng-nhóm-từ-quyết-định-có-tác-giả) explains use. `tools/build_event_groups.py` validates before creating a new private directory and writes `assembly.json`, `groups.jsonl`, `conflicts.jsonl`, `review_groups.md`, `run.json` and `checksums.json`. Run metadata records input/code/lock hashes, environment, author kinds and workflow counts. Existing destinations are refused.

## Apply local group review notes

`assembly_fingerprint` in `event_groups.py` hashes the canonical assembly with the same JSON settings as `annotation_sha256`. The offline HTML viewer binds browser notes to that fingerprint and exports `LocalGroupReviewNotes`. This is a draft feedback format, not the Label Studio human review ledger.

| Record | Contract |
|---|---|
| `GroupReviewNote` | Group ID, `not_seen` / `looks_ok` / `needs_check` / `suggest_split`, original text and timezone-aware update time |
| `LocalGroupReviewNotes` | Kind `local_group_review_notes`, `draft=true`, exact assembly fingerprint, timezone-aware export time and unique group entries not newer than the export |
| `GroupFeedbackResolution` | Explicit `ACCEPT`, `PARTITION` or `SEPARATE_CONTENT` plan, rationale, optional source evidence and member references |
| `AppliedGroupFeedback` | Original note, outcome, partitions, additional content references, affected pair IDs and assistant application attribution |
| `GroupFeedbackResult` | Source notes hash/fingerprint, derived pair records, application ledger and old group IDs absent from the submitted notes |

`apply_group_feedback` in [`group_feedback.py`](../src/labeling/group_feedback.py) rejects a stale fingerprint, duplicate/unknown groups, unresolved split requests and incomplete or overlapping partitions. It preserves input objects. `looks_ok` records acceptance at group scope; other pair metadata and authorship remain unchanged unless the application adds evidence or changes a decision. Cross-group pairs are not approved by acceptance of either group alone.

An explicit partition replaces crossing positive decisions with `DIFFERENT_EVENT`, clears their task/update relation and adds missing cross-partition negative pairs with source evidence. Within-partition task relations remain intact. `SEPARATE_CONTENT` keeps existing matched mentions while declaring additional source mentions for a caller to annotate and group separately; the caller must validate those annotations and build the resulting assembly before persisting an applied result. Free text is never parsed as an automatic split rule.

The original user group notes remain attributed to their source export. Structured pair decisions derived from a note use the assistant application author; no independent human pair annotation, private identity, approval or calibration result is inferred. New source mentions or subset changes require new annotation hashes; preserve old/new snapshots and prove that rebinding an old mention does not alter its event, arguments or spans.

`render_group_review` in [`group_viewer.py`](../src/labeling/group_viewer.py) validates source hashes, quote offsets and group/task references before embedding escaped JSON in a standalone local HTML template. It includes only source documents used by the assembly and omits `source_ref`. Optional feedback accepts one `GroupFeedbackResult` or an ordered list; every batch must match the assembly's pair records and resulting partitions. The last applied note per group takes precedence. Historical notes are shown separately from new browser notes; an applied `looks_ok` supplies the displayed approval unless a newer browser note overrides it.

`tools/render_group_review.py` accepts repeatable `--feedback` in that order and reads `tools/templates/group_review.html.template`. It writes a new HTML file plus input/output hashes under `reports/generated`, refusing existing destinations. Rendering does not change annotations or privacy clearance.
