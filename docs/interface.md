# Data and annotation contract

Annotations need stable evidence so every extracted task can be checked against its source. SmartNotice assigns offsets to normalized, redacted text and uses document IDs to connect raw provenance, annotations, and split assignments.

The Pydantic models in [`src/schemas.py`](../src/schemas.py) define accepted fields. JSON Lines files use UTF-8, one object per line. Unknown schema fields fail validation.

## Trace a document

The raw manifest records a relative `path`, `source_type` (`email` or `web`), `source_ref`, collection time, and optional `reference_date`, `selector`, `group_id`, `domain_holdout`, `synthetic`, and `pii_names`. Email collection requires `consent_ref`. Paths stay beneath the manifest directory. Name lists and consent references remain in private raw storage.

A prepared Notice contains the SHA-256 of the source bytes, a `doc_id` from its first 20 hex characters, source provenance, reference date and origin, redacted `text`, sentences, a hashed group ID, holdout/synthetic flags, and privacy review metadata. Email source references contain the content hash, not a participant address or local filename.

`reference_date` comes from the email Date header or a manually verified web publication date. Collection time is not a substitute. Missing or invalid email dates remain null. Numeric dates without years can borrow the reference year and are marked inferred; relative expressions require annotation review. The date helper does not infer a year rollover.

## Keep offsets stable

Offsets are zero-based, end-exclusive Python Unicode code point indices. `text[start:end]` must equal the stored sentence or span text. Normalize Unicode to NFC, redact identifiers, and segment before exporting annotation tasks. These offsets refer to the prepared text, not raw MIME bytes or DOM positions. The raw hash and manifest preserve source provenance.

Changes to prepared text invalidate existing annotation offsets. Browser exports must match the canonical text exactly. Check offsets after import, especially for pasted emoji or other non-BMP characters because browser indexing can differ from Python indexing.

## Describe an event

Each annotation contains an anonymized annotator ID, spans, events, and reviewed audience constraints. Span labels are ACTION, TIME, AUDIENCE, CONDITION, CHANNEL, and DOCUMENT. Each event references one ACTION, its argument spans, and at least one evidence sentence. Shared arguments can belong to several events. All linked spans must fit inside selected evidence sentences.

TIME arguments require START, DEADLINE, or EVENT_TIME. They may carry `normalized_date` and `inferred`. Other arguments cannot carry time metadata. An inferred date requires a reference date and a normalized value. A date interval uses separate TIME spans for its endpoints.

Each audience constraint references one AUDIENCE span and has a `scope`: `all_students`, `listed`, `implicit`, or `outside_population`. The population is university learners; institution names do not restrict it.

A `listed` constraint holds inclusion attributes: `degree_levels` (`undergraduate`, `master`, `doctoral`), `cohorts` as integer admission years or inclusive `cohort_min`/`cohort_max` bounds, `majors`, `programs`, and `statuses`. Status values come from `active`, `on_leave`, `suspended`, `defended`, and `graduated`. A constraint uses either the cohort list or the bounds. A `listed` constraint needs at least one inclusion attribute or `unrepresented=true`. An `all_students` constraint has no inclusion attributes. Both scopes may carry `excluded_statuses`. `implicit` and `outside_population` constraints carry no attributes. Validation rejects any other combination.

`unrepresented=true` records a reviewed audience requirement that profiles cannot express, such as a class code or role. Inclusion attributes combine with AND, values inside an attribute combine with OR, and separate audience branches combine with OR. Encode common exclusions in every branch. Curators resolve abbreviations to shared codes and convert years of study to admission years with the procedure in the [annotation protocol](annotation.md); the matcher only normalizes case and whitespace.

## Keep model suggestions and human reviews traceable

The LLM draft schema in `src/labeling/llm.py` contains quoted spans and events. A span specifies `span_id`, label, `sentence_id`, exact text, and an optional zero-based occurrence number. Python resolves the quote inside that sentence to canonical offsets. Missing quotes, ambiguous repeated quotes, invalid links, unsupported roles, duplicate IDs, and unlinked spans fail validation. Each ACTION has exactly one event; arguments may be shared. Empty span/event arrays represent a model prediction of no events, which also needs human checking.

`suggest-labels` writes Label Studio task JSON containing `data`, `data.proposal`, and `predictions`. `ProposalProvenance` in `src/schemas.py` owns the versioned run metadata: provider/model, run ID/time, prompt version/hash, text/source hashes, prediction hash, synthetic flag, temperature, and output-token limit. Predictions are distinct from canonical Annotation JSONL. Failures follow `LabelingFailure` and contain a document ID, provider/model, attempt time, and safe reason. Failed records cannot become review predictions.

Real notices require a `ProviderApproval` JSONL row matching the prepared-text hash, document ID, provider, recorded reviewer/time, privacy clearance, and provider-use permission. The prepared privacy flag does not satisfy this requirement. The [LLM review procedure](llm-labeling.md) owns the approval and provider configuration steps.

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

Any group containing a reserved web notice is removed from the ordinary pool. Its web documents receive `domain_test`; related email receives `excluded`. Persist assignments and review group merges before training. Synthetic flags travel with every notice and derived pair.
