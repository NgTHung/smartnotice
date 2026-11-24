# LightGBM applicability features and GroupKFold harness, 2026-11-24

The applicability comparison in [issue #8](https://github.com/NgTHung/smartnotice/issues/8) needs a feature-based model between the reviewed audience rules and the BamiBERT cross-encoder. This design covers the LightGBM feature layer and a grouped cross-validation harness that produce recorded, leakage-checked runs. It is a dated plan; the [data contract](../../interface.md) and [evaluation protocol](../../evaluation.md) remain the owners of persisted formats and measurement rules.

## Intent

A LightGBM model predicts APPLIES, NOT_APPLIES, or UNCLEAR for one event and one synthetic profile. Silver labels come from `build_pairs`, which applies reviewed `AudienceConstraint` rows to profiles. The model never sees those constraints, so it has to recover the audience from text and compare it with the profile. Issue #8 also requires running the feature model on human-annotated and on predicted audiences so propagated extraction errors can be measured.

The BamiBERT system belongs to another owner. This work only offers suggestions to that owner and builds nothing for it.

## Goals

- Engineer features from audience text, event text, and the profile that let a tree model compare audiences with profiles, including cohorts absent from training.
- Support three audience sources with one feature path: human-annotated AUDIENCE/CONDITION spans, predicted spans in the same `Annotation` schema, and event text alone.
- Provide a GroupKFold harness over the ordinary training pool with repeated seeds, out-of-fold predictions, metrics with denominators, and a complete run record.
- Provide an ablation between cue/cross features alone and cue/cross features plus TF-IDF.
- Measure whether email helps or hurts web applicability with a training-mix experiment on fixed folds, and report email and web results separately.
- Measure whether the web pool is large enough with a learning curve over web groups.
- Treat the missing-audience policy as an input of each run, recorded and comparable across runs.

## Non-goals

- BamiBERT inputs or training.
- Scoring `test` or `domain_test`. The model is frozen before those sets are measured under [issue #9](https://github.com/NgTHung/smartnotice/issues/9), and their gold annotations do not exist yet.
- Temperature scaling and abstention thresholds (issue #9). The harness saves out-of-fold class probabilities so calibration can use them later.
- Changes to pair or profile generation (issue #17), the rules baseline (issue #8), and an extraction model that produces predicted audiences (issues #5 and #6).
- An API or web integration.

## Anti-goals

The work fails, even if it runs, when:

- any model input contains constraint fields, `rule_reason`, `label_origin`, `audience_policy`, `audience_default_applied`, or annotation/profile-set hashes;
- a pair is split independently of its document, or a group crosses folds;
- TF-IDF vocabularies, lexicon contents, or any fitted statistic use data outside the training fold;
- the harness reads `test`, `domain_test`, or `excluded` documents for training or selection;
- a cross-validation score is reported as a held-out estimate, or silver-label metrics are described as human agreement;
- a synthetic fixture result is presented as model quality.

## Constraints

- Use the frozen [split v3.3](../../../data/annotations/split_65_15_20_v3_3_2026-11-15/README.md) assignments. Pairs inherit the split and `group_id` of their `doc_id`.
- Train split v3.3 contains 1,516 events: 504 without AUDIENCE, 208 with CONDITION. Its constraints are 348 `all_students`, 224 `listed` with `unrepresented=true`, 80 `listed`, and 5 `outside_population`. They use 5 major codes and 7 program codes. These counts describe machine-assisted, user-reviewed annotations, not gold labels. With so few distinguishing constraints, features must generalize by comparison, not by memorizing values.
- Email and web differ in how often the text states its audience. Email writers usually know the recipients through the mailing list, which preparation removes with the headers for privacy. Train split v3.3 event counts (machine-assisted, user-reviewed annotations; categories overlap because an event can have several audiences):

  | | Email (281 docs) | Web (122 docs) |
  |---|---:|---:|
  | Events | 1,022 | 494 |
  | No AUDIENCE | 437 (43%) | 67 (14%) |
  | `all_students` audience | 367 (36%) | 44 (9%) |
  | `listed` or `outside_population` audience | 222 (22%) | 383 (78%) |
  | CONDITION argument | 57 (6%) | 151 (31%) |

  Most email events receive the same label for every profile, so profile-comparison signal comes mainly from web. Email remains in scope because the application accepts `.eml` input.
- The train+validation pool has 150 web documents in 115 groups; 97 groups contain a `listed` audience, with 77 distinct `listed` constraints. Web groups per `listed` attribute: cohort list 39, degree 37, status 19, cohort bounds 12, major 9, program 7. Email adds 94 groups with `listed` audiences but only 29 distinct constraints. Program, major, and cohort-bound comparisons therefore have few independent examples, and five-fold per-attribute results for them will be unstable.
- Keeping a coarse mailing-list category from email headers would change the data contract and need privacy review. It is a team decision outside this design.
- Cohort normalization follows the [annotation protocol](../../annotation.md): "K24" means admission year 2024, ranges use inclusive bounds, and a year of study needs `reference_date` with the September boundary and the July 1 to October 15 abstention window.
- Profiles should come from training-pool constraints. `generate_profiles` takes its value pool from the constraints it receives, so profiles built from test constraints would expose test cohorts and codes. The harness records `profile_set_sha256` but cannot verify which constraints produced the profiles; issue #17 owns that step.
- Use `uv add` for `scikit-learn` (≥1.6, for seeded `GroupKFold` shuffling) and `lightgbm`, committing `pyproject.toml` with the regenerated `uv.lock`.

## Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| A. Hand-built audience cues plus profile-vs-text features | Interpretable, generalizes to unseen cohorts, works with little data. The cue extractor resembles the curators' normalization, and cues it misses are invisible. | Core of the chosen design |
| B. Generic TF-IDF of event text plus profile one-hot | Little engineering. Trees cannot learn that a year in the text equals the profile's year, so the model memorizes values and fails on unseen cohorts. | Rejected |
| C. A plus a fold-fitted TF-IDF block | Keeps A's comparison features and lets the model use scope and condition wording that the cues miss. Gives a report-ready ablation. | Chosen by the user |

## Design

### Package layout

A new package `smartnotice.modeling` maps to `src/modeling/`:

| File | Responsibility |
|---|---|
| `src/modeling/applicability_features.py` | Model input view, cue extraction, cross features, feature matrix assembly, TF-IDF wrapper |
| `src/modeling/applicability_training.py` | Data joining and validation, GroupKFold loop, LightGBM fitting, metrics, run record |
| `config/applicability_lexicon.json` | Versioned code and cue vocabulary |

`src/cli.py` gains `train-applicability`. Add `smartnotice.modeling` to the setuptools package list and an owner row to the architecture table in `AGENTS.md`.

### Model input view

`ApplicabilityInput` is a Pydantic model and the only object that feature code receives:

- `doc_id`, `event_id`, `profile_id` (identifiers, never features);
- `event_text`;
- `audience_texts` and `condition_texts`, each a list of span texts for the event, or `None` in event-text-only mode;
- `reference_date` and `source_type` (`email` or `web`) from the notice;
- profile fields `cohort`, `degree_level`, `major`, `program`, `status`.

`build_inputs(pairs, notices, audience_annotations, mode)` constructs inputs by allowlist. It fails with the pair's line number when a document, event, or span reference is missing. In `human` and `predicted` modes, the AUDIENCE and CONDITION spans come from the event's arguments in the supplied annotation file, including inherited audience spans created by `apply_audience_scope`. A test passes a pair row containing every forbidden key and checks that none reaches the input or the feature names.

### Audience cues

`extract_audience_cues(texts, reference_date, lexicon)` returns an `AudienceCues` record. Matching uses NFC text with case and whitespace folding; diacritics are preserved.

| Cue | Source patterns |
|---|---|
| Cohort years | `K24`, `khóa 2025`, two-digit years 15–35 as 20NN |
| Cohort bounds | `từ K22 đến K24`, `K24 về trước`, `trở về trước`, `trở đi`, `trở lên` |
| Year of study | `năm thứ N`, `năm N`, converted with `reference_date` under the protocol rule; inside the abstention window or without a date it sets `cohort_unresolved` |
| Degree | undergraduate, master's, doctoral terms; generic graduate terms map to master's and doctoral |
| Major, program | lexicon surface forms for each code |
| Status | lexicon status terms |
| Excluded status | exclusion words (`trừ`, `ngoại trừ`, `không bao gồm`, `không áp dụng`) followed by a status term in the same clause |
| All students | `toàn thể`, `tất cả sinh viên`, and lexicon equivalents |
| Outside population | staff, lecturer, and parent terms without a student term |
| Unrepresented requirement | class codes, roles such as `lớp trưởng` or `ban cán sự`, training mode such as `hệ chính quy`, `năm cuối` |
| Condition | lexicon condition words on `condition_texts`, or on `event_text` in event-text-only mode |
| Absence | no audience text, or no explicit cue found |

The protocol's new-intake anchoring rule (rule 1) is out of scope for the first version; such cases fall back to the window and boundary rules or remain unresolved.

### Features

Each pair yields one feature row:

- **Cue features** (event-level): mention flags and counts for each attribute, cohort bound presence, `cohort_unresolved`, all-students, outside-population, unrepresented, condition, absence, number of audience and condition spans, and audience text length.
- **Source feature**: one-hot `source_type`. It is notice metadata that the application also knows (`.eml` versus URL), not label provenance. `--no-source-feature` removes it for an ablation.
- **Profile features**: a known/missing flag for each attribute, and one-hot `degree_level` and `status`. Raw cohort, major, and program values are excluded so the model cannot memorize them.
- **Cross features** (pair-level): for each attribute, `mentioned`, `profile_known`, `match`, `conflict`, and `required_but_unknown`. Cohorts add `in_range`, `below_min`, `above_max`, and the absolute distance in years to the nearest mentioned year. Status adds `excluded_status_hit`. Aggregates are `any_conflict`, `all_mentioned_match`, `n_mentioned`, and `n_required_unknown`.
- **TF-IDF block** (optional): word unigrams and bigrams of `event_text`, fitted on the distinct events of the training fold only, with `min_df=2` and at most 1,000 features. These features are profile-independent and shift event-level tendencies such as UNCLEAR.

`FeatureBuilder.fit(train_inputs)` / `.transform(inputs)` returns a sparse matrix and ordered feature names. Only the TF-IDF block is fitted; the lexicon is fixed configuration.

### Lexicon

`config/applicability_lexicon.json` has a `version`, the code-to-surface-form maps for majors and programs, and the degree, status, exclusion, all-students, outside-population, unrepresented, and condition word lists. The first draft takes codes from training-split constraints and examples in the annotation protocol (for example `CLC` → "chất lượng cao"). Surface forms need team review, and the run record stores the file's SHA-256. The lexicon must not be expanded by reading test or domain-test text.

### Harness

`smartnotice train-applicability --pairs ... --notices ... --assignments ... --audience-source {human,predicted,none} [--audience-annotations ...] [--train-sources email web] [--learning-curve 0.25 0.5 0.75 1.0] [--seeds 42 43 44] [--folds 5] [--tfidf/--no-tfidf] [--no-source-feature] [--params params.json] [--weighting {event,pair}] [--fit-final] [--output-dir ...]`

1. Load and validate inputs. Join each pair to its assignment. Stop when any pair's document is in `test`, `domain_test`, or `excluded`, or is missing from the assignments. Exclude synthetic pairs unless `--allow-synthetic` is passed; tests use that flag.
2. The pool is the `train` and `validation` splits, as the split v3.3 README specifies.
3. Read the missing-audience policy from the pairs: rows either all carry `audience_policy=assume_all_students_without_audience` or all omit it. Stop on a mixture. Record the policy in the run record, so runs under each policy can be compared on the same folds.
4. For each seed, `GroupKFold(n_splits=folds, shuffle=True, random_state=seed)` on `group_id` over the whole pool, email and web together. Record fold membership per group. Verify that no group crosses folds. Folds do not depend on `--train-sources` or the learning-curve fraction, so every training mix is scored on the same held-out events.
5. In each fold, keep the training-fold pairs whose source is in `--train-sources` (default both). With `--learning-curve`, also keep a seeded random fraction of the training fold's web groups, with nested subsets so a larger fraction contains every smaller one. Fit `FeatureBuilder` on the kept pairs, train a multiclass `LGBMClassifier` with `random_state=seed`, and predict class probabilities for the whole held-out fold.
6. Weighting defaults to `event`: each pair weighs 1/(number of profiles for its event), so the profile count does not dominate. `pair` weighting is available for comparison.
7. Parameters come from a JSON file with recorded defaults. When a grid is given, selection uses mean out-of-fold macro-F1, and the record marks the score as a selection score, not a held-out estimate.
8. `--fit-final` trains on the whole pool with the selected parameters. It saves the LightGBM text model and the TF-IDF vocabulary and IDF weights as JSON. No test data is scored.

A majority-class baseline is computed on the same folds as a sanity reference.

The planned comparisons, all on the same folds and seeds:

- **Training mix**: web only, email only, and both, scored on held-out web events and on held-out email events. This complements the domain-transfer comparison in the evaluation protocol, which uses the reserved web set under issue #9.
- **Learning curve**: web-only training at increasing web-group fractions, scored on held-out web events. A curve that still rises at the full pool indicates that more web collection (issue #15) would help; a flat curve does not show that the data are sufficient for unseen institutions.
- **Ablations**: without TF-IDF, and without the source feature.
- **Missing-audience policy**: the same configuration on pairs built with and without the default.

### Metrics

For each seed and fold, and for the pooled out-of-fold predictions: three-way macro-F1, per-class precision/recall/F1, the confusion matrix, and APPLIES recall. Each is computed event-weighted and pair-weighted, with denominators. Subsets defined by `rule_reason` (used only for slicing, never as input) include exclusion (`excluded_status`), implicit audience (`implicit_audience`), missing audience (`no_audience_constraint`, `assumed_all_students_no_audience`), and condition (`unmodeled_condition`). Every metric is also reported separately for email and web held-out events, and for profile-dependent events, meaning events whose silver label differs across profiles. This subset keeps constant-label events, which are common in email, from inflating the overall score. Per-fold counts of `mismatched_<attribute>` reasons show how many examples support each attribute comparison. Mean and standard deviation across seeds. Every metric file states `label_origin: constraint_rule`.

### Run record

Each run writes a new directory, by default `reports/generated/applicability/<run_id>/`, and refuses to overwrite an existing one:

- `record.json`: run ID and time, CLI configuration, seeds, folds, parameters, weighting, audience source, training sources, learning-curve fractions and their selected web groups, missing-audience policy, git commit and dirty flag, `uv.lock` SHA-256, SHA-256 of every input file and of the lexicon, the distinct `annotation_sha256` and `profile_set_sha256` values in the pairs, any `audience_policy`, Python/LightGBM/scikit-learn versions, platform, and per-fold document/event/pair/label counts;
- `folds.jsonl`: seed, `group_id`, fold;
- `oof_predictions.jsonl`: seed, fold, `doc_id`, `event_id`, `profile_id`, gold label, predicted label, class probabilities;
- `metrics.json`;
- `feature_names.json` and LightGBM gain importances per fold;
- final model files when `--fit-final` is set.

### Contract and documentation updates

- `docs/interface.md`: the model-input allowlist and the run-record files above.
- `README.md`: the `train-applicability` command.
- `AGENTS.md`: the `src/modeling/` owner row.

### Tests

Synthetic, hand-checkable inputs without network access:

- cue extraction for each pattern row, including bounds, year-of-study conversion on both sides of the September boundary and inside the abstention window, and exclusion clauses;
- cross features for match, conflict, missing, in range, and out of range;
- the forbidden-key allowlist test;
- TF-IDF fitted only on training-fold events (a token present only in the held-out fold is absent from the vocabulary);
- the harness stops on test or domain-test pairs, missing joins, and mixed missing-audience policies; keeps groups within folds; produces identical folds for every `--train-sources` value and learning-curve fraction; builds nested learning-curve subsets; produces identical results for the same seed; and writes a complete run record on a tiny fixture with `--allow-synthetic`.

## Left to the builder

- Exact regular expressions and lexicon entries, within the rules above.
- Default LightGBM parameters, recorded in the params file.
- Internal function boundaries inside the two modules.

## Calls made without explicit user decision

- CV pool is `train` plus `validation`, following the split v3.3 README; issue #9 can calibrate on out-of-fold probabilities.
- In `human` and `predicted` modes, CONDITION span texts feed the condition cues, mirroring the rules baseline.
- Raw cohort, major, and program values are excluded from features.
- Event weighting is the default.
- Plain `GroupKFold` with seeded shuffling, matching the evaluation protocol, rather than `StratifiedGroupKFold`.
- `scikit-learn` and `lightgbm` become main dependencies because the CLI command imports them.
- New-intake cohort anchoring is deferred.
- `source_type` is an input feature, with an ablation that removes it.
- Folds are fixed on the whole pool, and training mixes and learning-curve fractions only filter training folds.
- "Profile-dependent events" are defined from silver labels for reporting only.

## Decided by the user

- Approach C with a GroupKFold harness; BamiBERT is out of scope.
- Email stays in training as an experiment: training mixes, per-source reporting, and the source feature.
- The missing-audience policy is an open input of each run.
