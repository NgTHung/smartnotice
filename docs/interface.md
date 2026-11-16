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

### Plan folds from reviewed events

`tools/plan_group_folds.py` reads a frozen JSONL with one row per `doc_id`, a group assembly, and the notes export for that exact assembly. The input `FrozenGroupAssignment` requires `doc_id`, `group_id` (20 lowercase hex characters), `split` and a SHA-256 `text_sha256` of the UTF-8 prepared text. It also accepts `data_sha256`, `seed` and `similarity`. A row without a prepared text hash cannot establish that the review and assignment describe the same snapshot.

`plan_group_folds` checks the notes fingerprint, resolves each assembly mention against the frozen text hash and verifies that the groups partition the assembly mentions. Only `looks_ok` groups contribute reviewed event links. Free text stays in the source notes. Frozen document groups and reviewed event links form connected components over documents, including when one document contains mentions in multiple event groups. Only components entirely in `train` can enter cross-validation. Fewer eligible groups than requested folds is an error.

The runner writes these records to a new directory under `reports/generated`:

| File | Contents |
|---|---|
| `fold_assignments.jsonl` | One row per frozen document, preserving `doc_id`, `group_id` and `split`; `fold_group_id` hashes the sorted component's document IDs. `fold` is the zero-based validation fold; null means ineligible, with `exclusion_reason` of `outside_train` or `linked_to_outside_train`. |
| `reviewed_event_links.jsonl` | Assembly event group ID and distinct document IDs for each accepted group with more than one document. |
| `split_conflicts.jsonl` | The derived component ID and its document IDs by frozen split for each component spanning splits. |
| `provisional_review_queue.jsonl` | Optional proposed event groups with more than one document, their frozen splits and assigned CV folds. Proposals never affect assignments. |
| `run.json`, `checksums.json` | Grouping and fold counts, algorithm, seed, Python version, input/code/lock hashes, notes fingerprint and output hashes. |

Join event or profile pair records by `doc_id` and inherit the assigned fold. The [evaluation procedure](evaluation.md#plan-group-k-fold-from-reviewed-events) explains how to use the plan and handle conflicts before evaluation.

`allocate_group_folds` takes prepared assignments and explicit lists of document IDs to keep together. It checks that each referenced document exists. Callers can supply a precautionary constraint for an unresolved event link. Record the reason outside the fold assignments and exclude the constraint from event labels.

### Score pairs for shared event identity

`GroupingModelMention` contains `mention_id`, `doc_id`, the mention version, action event, spans and evidence sentences. The runner validates exact source offsets and hashes before constructing features. Pair rows name two mention IDs in `left` and `right` and give a unique `review_id` and a `decision`. The train export also records `left_fold`, `right_fold` and `same_event`. These fields must agree with the frozen assignments and decision. Evaluation can retain `UNCLEAR` with a null target.

`GroupingLinearModel` stores the ordered feature names, scaling means and standard deviations, weights, intercept and decision threshold as JSON. The model predicts a single score for shared event identity. `SAME_EVENT` and `UPDATE_OF` both supply positive examples. The score supports pair ranking. Event assembly and update direction follow their respective contracts.

Checkpoints identify the feature version with `kind`. `grouping-logistic-v2` adds evidence from sentences near the mention. Its predictions include `ungated_logistic` for the raw thresholded score and `decision` for the policy output. A merge proposal requires corroboration such as an explicit event code or shared date with matching topic. The policy also recognizes closely dated requests and replies with a shared distinctive phrase. Conflicting explicit terms or event codes block a proposal. `anchor` records the source cue category when found. Handle `UNCLEAR` through review. Neither document group IDs nor the origin of labels are model features.

When the evaluator receives `--raw-email-dir`, it verifies available `<raw_sha256>.eml` sources and adds `followup_title`, `followup_reference` and `followup_combined` to the v2 predictions. These booleans describe proposals for shared event identity. The evidence object contains title sentence IDs on either side, an optional direction and gap in seconds, equality of the sender mailbox, and whether a parent reference resolves to the other message. Raw addresses, absolute send times and message IDs stay in memory. A missing source or a timezone-free `Date` disables the minute comparison. A gap of 1–900 seconds supplies a candidate cue. A proposal based on that cue also needs continuation wording and corroborating content. A proposal for a shared event carries no decision about which field a later email changes.

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

## Propose and assemble groups automatically

`propose_event_groups` in [`automatic_grouping.py`](../src/labeling/automatic_grouping.py) takes Notice records, validated Annotations, a timezone-aware `generated_at`, optional `AutomaticGroupingConfig` and optional attributed `TimeBoundaryReview` records. It uses the same mention snapshots and source quotes as `build_event_groups`. Pair reviews, approved group membership and a reference assembly are excluded from prediction inputs. Existing annotation and boundary authorship remains intact.

| Record | Contract |
|---|---|
| `AutomaticGroupingConfig` | Unfitted lexical candidate Jaccard threshold `(0, 1]`, default `0.35`; minimum shared lexical tokens, default `3`; minimum informative identity tokens, default `2`, at least `2` |
| `AutomaticPairProposal` | `origin=rule_proposal`, candidate reasons, decision reasons, lexical similarity and a source-backed `GroupingReview`; human pair authorship is rejected |
| `AutomaticGroupingResult` | Rule version `automatic-event-grouping-v1`, config, timezone-aware generation time, total pair count, proposals and provisional `EventGroupAssembly` |
| `GroupingPairComparison` | One explicit reference pair, expected/proposed decision and task relation, resulting group/task membership and mismatch reasons; missing candidates have null proposed fields |
| `AutomaticGroupingComparison` | Kind `grouping_development_comparison`, exact reference fingerprint, compared pairs and `independent_evaluation=false` |

Candidate reasons combine shared explicit codes/titles, informative ACTION overlap, source URLs and lexical evidence overlap. URL sharing and lexical similarity alone cannot establish event identity. Identity requires a shared explicit event code, or a distinctive name with a matching explicit period or full-date anchor. Sender and document-level collection groups do not supply identity. Features use each mention's selected evidence sentences, not the whole email; ambiguous evidence containing multiple event codes or numbered specialties abstains. This is a fixed rule baseline without fitted features or calibrated probabilities.

Different explicit periods, event codes or numbered specialty titles can produce `DIFFERENT_EVENT`. Other unresolved identity produces `UNCLEAR`. Task families and ACTION identity distinguish repetitions from separate tasks; annotated conditions and named sessions preserve distinct obligations. Time conflicts are checked within `SAME_TASK`, not across registration, attendance and other tasks. Unrecognized task families remain `UNRESOLVED` rather than being assumed equivalent.

An automatic `UPDATE_OF` requires matching identity/task, explicit change language on exactly one side and unique annotated old/new time evidence for each changed field. The explicit change source is left/new; email ordering alone does not establish direction. An absent old field is recorded as null. Interval/invalid-date ambiguity, unresolved update direction, and location/status changes abstain. Original qualifiers, quotes and offsets remain in facts; different deadline qualifiers are not silently equated. The builder preserves all source values and update history.

Every pair inside an initially positive connected component is classified, including pairs omitted by candidate retrieval. Contradictions reach the builder's quarantine behavior. Proposals use `reviewer_id=automatic_grouping_rules_v1`, the existing nonhuman `reviewer_kind=ai_assistant`, and explicit rule origin/rationale; no human review or group approval is created. Group and privacy review flags remain true.

`compare_grouping_reference` requires the same mention set and exact source/annotation versions. It compares only explicit reference pairs and records missing candidates, decision/task mismatches, update direction/quotes and resulting group/task mismatches. It does not derive negative pairs from singletons or group approval. The reference is read after predictions in `tools/run_automatic_grouping.py`, so supplying it cannot change predictions.

The runner accepts exactly one of `--annotations` for canonical Annotation JSONL or `--predictions` for saved Label Studio prediction tasks. Prediction tasks must cover exactly the supplied Notice set, with one prediction per document and matching source/text/prediction hashes. `import_prediction_tasks` owns conversion and preserves `model_prediction` authorship. Empty predictions produce empty annotations. Invalid batches fail before an output directory is created.

The runner validates and renders before creating a new directory under `data/processed` or `reports/generated`; it refuses existing destinations. Outputs are `annotations.jsonl`, `result.json`, `pair_proposals.jsonl`, `pair_decisions.jsonl`, `assembly.json`, `groups.jsonl`, `conflicts.jsonl`, `index.html`, `run.json` and `checksums.json`. The annotation snapshot includes empty records and retains supplied authorship. A supplied reference adds `comparison.json` and `comparison.md`. Run metadata records source/code/template/lock hashes, generation time, environment, config, document/annotation/empty-annotation counts, workflow counts, diagnostic counts and provenance limits. Prediction input uses `label_origin=rule_proposals_over_model_predictions`; canonical input uses `rule_proposals_over_supplied_annotations`. `--generated-at` permits exact replay with unchanged inputs and implementation. No saved approvals, input records or split assignments are overwritten.

## Apply local group review notes

`assembly_fingerprint` in `event_groups.py` hashes the canonical assembly with the same JSON settings as `annotation_sha256`. The offline HTML viewer binds browser notes to that fingerprint and exports `LocalGroupReviewNotes`. This is a draft feedback format, not the Label Studio human review ledger.

| Record | Contract |
|---|---|
| `GroupReviewNote` | Group ID, `not_seen` / `looks_ok` / `needs_check` / `suggest_split`, original text and timezone-aware update time |
| `LocalGroupReviewNotes` | Kind `local_group_review_notes`, `draft=true`, exact assembly fingerprint, timezone-aware export time and unique group entries not newer than the export |
| `GroupFeedbackResolution` | Explicit `ACCEPT`, `PARTITION` or `SEPARATE_CONTENT` plan, rationale, optional source evidence and member references |
| `GroupMergeResolution` | At least two distinct existing group IDs, a distinct-task/session/conditional relation, rationale and optional evidence; each selected group requires a submitted note |
| `GroupFeedbackPlan` | Explicit resolutions, group merges and source-backed display labels; free text is not parsed to infer these choices |
| `AppliedGroupFeedback` | Original note, outcome, partitions, additional content references, affected pair IDs and assistant application attribution |
| `GroupFeedbackResult` | Source notes hash/fingerprint, derived pair records, application ledger and old group IDs absent from the submitted notes |

`apply_group_feedback` in [`group_feedback.py`](../src/labeling/group_feedback.py) rejects a stale fingerprint, duplicate/unknown groups, unresolved split requests and incomplete or overlapping partitions. It preserves input objects. `looks_ok` records acceptance at group scope; other pair metadata and authorship remain unchanged unless the application adds evidence or changes a decision. Cross-group pairs are not approved by acceptance of either group alone.

Optional `merges` explicitly joins groups representing different steps of one event. A merge replaces every crossing decision with `SAME_EVENT` and the supplied distinct-task relation, adding missing pairs with source evidence. Within-group decisions remain intact. A group cannot appear in overlapping merges, merge with an unread group, or both split and merge in one application. The result records `outcome=merged` for each original note and the complete resulting membership; original note statuses and timestamps remain intact. A `needs_check` note can be resolved by an explicit merge plan, never by interpreting its prose automatically.

An explicit partition replaces crossing positive decisions with `DIFFERENT_EVENT`, clears their task/update relation and adds missing cross-partition negative pairs with source evidence. Within-partition task relations remain intact. `SEPARATE_CONTENT` keeps existing matched mentions while declaring additional source mentions for a caller to annotate and group separately; the caller must validate those annotations and build the resulting assembly before persisting an applied result. Free text is never parsed as an automatic split rule.

The original user group notes remain attributed to their source export. Structured pair decisions derived from a note use the assistant application author; no independent human pair annotation, private identity, approval or calibration result is inferred. New source mentions or subset changes require new annotation hashes; preserve old/new snapshots and prove that rebinding an old mention does not alter its event, arguments or spans.

`render_group_review` in [`group_viewer.py`](../src/labeling/group_viewer.py) validates source hashes, quote offsets and group/task references before embedding escaped JSON in a standalone local HTML template. It includes only source documents used by the assembly and omits `source_ref`. Optional feedback accepts one `GroupFeedbackResult` or an ordered list; every batch must match the assembly's pair records and resulting partitions. The last applied note per group takes precedence. Historical notes are shown separately from new browser notes; an applied `looks_ok` supplies the displayed approval unless a newer browser note overrides it.

When several original notes map to one merged group, the viewer retains each in `source_notes` and displays the combined text. A merged group starts with `needs_check` for reviewing the changed result; acceptance of its former groups does not silently approve the combined membership.

`GroupDisplayLabel` contains a group ID, title, supporting quotes and author. `GroupDisplayLabels` binds those labels to an exact assembly fingerprint. The renderer rejects unknown/duplicate groups, quotes outside member documents and titles that differ from all quoted titles after case/whitespace normalization. Naming a group changes neither its tasks nor its assembly fingerprint. Such labels can name a campaign whose existing tasks describe only a ceremony.

`tools/render_group_review.py` accepts repeatable `--feedback`, optional `--labels`, and reads `tools/templates/group_review.html.template`. It writes a new HTML file plus input/output hashes under `reports/generated`, refusing existing destinations. Rendering does not change annotations or privacy clearance.

`tools/apply_group_review.py` accepts the viewed assembly, matching Notices/Annotations, exported notes and a `GroupFeedbackPlan`. It first reproduces the viewed assembly, then applies resolutions, builds and renders the result before creating a new private output directory. It supports accepting, partitioning and merging existing mentions; `SEPARATE_CONTENT` requires a separate validated annotation migration. Outputs retain the byte-identical source notes/plan, feedback ledger, pair reviews, assembly/groups/conflicts, display labels, HTML, run metadata and checksums. `--applied-at` enables exact replay. Source records, original approvals and previous pages are never replaced.
