# LightGBM Applicability Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build leakage-checked applicability features and a GroupKFold LightGBM harness that records every run.

**Architecture:** `smartnotice.modeling.applicability_features` turns build-pairs rows into allowlisted `ApplicabilityInput` records, extracts audience cues, and assembles cue, profile, cross, source, and optional fold-fitted TF-IDF features. `smartnotice.modeling.applicability_training` validates the pool, assigns seeded group folds over the whole pool, filters training folds by source and learning-curve fraction, fits LightGBM, computes metrics, and writes a run directory. `smartnotice train-applicability` calls the harness.

**Tech Stack:** Python 3.12, Pydantic 2, scikit-learn ≥1.6 (`TfidfVectorizer`, `GroupKFold`, metrics), LightGBM, SciPy sparse matrices, pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-lightgbm-applicability-features-design.md`

## Global Constraints

- Model inputs never contain constraint fields, `rule_reason`, `label_origin`, `audience_policy`, `audience_default_applied`, `annotation_sha256`, or `profile_set_sha256`.
- Pairs inherit `split` and `group_id` from `assignments.jsonl` by `doc_id`; the pool is `train` + `validation`; any `test`, `domain_test`, `excluded`, or unassigned pair stops the run.
- Folds: `GroupKFold(n_splits=folds, shuffle=True, random_state=seed)` on `group_id` over the whole pool, independent of `--train-sources` and learning-curve fraction.
- TF-IDF: word unigrams+bigrams of `event_text`, `min_df=2`, `max_features=1000`, fitted on distinct training-fold events only.
- Raw cohort, major, and program values are not features.
- Default seeds `[42, 43, 44]` start from `DEFAULT_SEED`; default folds 5; default weighting `event` (1 / profiles per event).
- Label order `["APPLIES", "NOT_APPLIES", "UNCLEAR"]`; every metric file states `label_origin: constraint_rule`.
- Run directory default `reports/generated/applicability/<run_id>/`; refuse to overwrite.
- Synthetic pairs are excluded unless `allow_synthetic=True`.
- UTF-8 everywhere, `pathlib.Path`, docstrings on public functions, descriptive `ValueError` with line number or IDs.

## Review Focus

- Pairs JSONL with mixed missing-audience policy rows: stop with a message naming the policy conflict (Task 5 test `test_mixed_policy_stops`).
- A held-out fold with no example of some class: metrics still report all three classes with zero support, not crash (Task 5 test `test_metrics_with_absent_class`).
- A fold whose training part has no web group after `--train-sources web` with a small fraction: stop with a message naming seed and fold rather than fitting on nothing (Task 5 test `test_empty_training_fold_stops`).
- An event whose AUDIENCE span text appears in human mode but the notice lacks `reference_date`: year-of-study cues set `cohort_unresolved`, never a guessed year (Task 3 test `test_study_year_without_reference_date_is_unresolved`).
- Existing output directory: refuse before any computation (Task 5 test `test_existing_run_dir_refused`).

---

### Task 1: Dependencies, package, lexicon

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add "scikit-learn>=1.6,<2" "lightgbm>=4.5,<5"`)
- Modify: `pyproject.toml` `[tool.setuptools] packages` add `"smartnotice.modeling"`
- Create: `src/modeling/__init__.py`, `src/modeling/lexicon.py`, `config/applicability_lexicon.json`
- Test: `tests/test_applicability_features.py`

**Interfaces:**
- Produces: `Lexicon` (Pydantic, `extra="forbid"`) with `version: str`, `majors: dict[str, list[str]]`, `programs: dict[str, list[str]]`, `degrees: dict[DegreeLevel | "graduate", list[str]]`, `statuses: dict[StudentStatus, list[str]]`, `exclusion: list[str]`, `all_students: list[str]`, `outside_population: list[str]`, `student_terms: list[str]`, `unrepresented: list[str]`, `condition: list[str]`; `load_lexicon(path: Path) -> tuple[Lexicon, str]` returning the lexicon and the file SHA-256; `DEFAULT_LEXICON_PATH`.

- [ ] Step 1: Test `test_lexicon_loads_with_hash` (default file loads; hash is 64 hex; `"CLC"` in `programs`), `test_lexicon_rejects_unknown_key` (extra key → `ValidationError`), `test_lexicon_rejects_blank_surface_form` (`""` → `ValueError`).
- [ ] Step 2: Run `uv run pytest tests/test_applicability_features.py -v`; expect import failure.
- [ ] Step 3: `uv add`, package list, `lexicon.py`, JSON. Codes are the train-split codes: majors `CNTT, HOA_HOC, KTMT, TTNT, TCNH`; programs `TCTA, CLC, VIET_PHAP, TIEN_TIEN, DAI_TRA, DE_AN, CHUAN`. Surface forms are lowercase NFC, marked for team review by `"version": "draft-2026-11-24"`.
- [ ] Step 4: Tests pass.
- [ ] Step 5: Commit `feat: add applicability lexicon and modeling dependencies`.

### Task 2: Model input view

**Files:**
- Create: `src/modeling/applicability_features.py`
- Test: `tests/test_applicability_features.py`, helper `tests/applicability_fixture.py`

**Interfaces:**
- Consumes: `Notice`, `Annotation`, `validate_annotation`.
- Produces: `AudienceSource = Literal["human", "predicted", "none"]`; `ApplicabilityInput(Record)` fields `doc_id, event_id, profile_id, event_text, audience_texts: list[str] | None, condition_texts: list[str] | None, reference_date: date | None, source_type, cohort, degree_level, major, program, status`; `build_inputs(pairs: list[dict], notices: list[Notice], annotations: list[Annotation] | None, source: AudienceSource) -> list[ApplicabilityInput]`. Fixture helper `make_corpus(n_docs, web_every, seed) -> (notices, annotations, profiles, pairs, assignments)` built with real `build_pairs`.

- [ ] Step 1: Tests `test_inputs_exclude_label_provenance` (row containing every forbidden key → none appear in `model_dump()`), `test_human_source_uses_event_audience_and_condition_spans`, `test_none_source_has_no_span_texts`, `test_missing_event_reports_line` (`ValueError` containing `"pair line 1"`), `test_annotation_required_for_span_sources`.
- [ ] Step 2: Run; expect failure.
- [ ] Step 3: Implement; validate each annotation against its notice once.
- [ ] Step 4: Pass.
- [ ] Step 5: Commit `feat: build allowlisted applicability inputs`.

### Task 3: Audience cues

**Files:** Modify `src/modeling/applicability_features.py`; test same file.

**Interfaces:**
- Produces: `admission_year_for_study_year(year_of_study: int, reference_date: date | None) -> int | None` (Sep boundary; `None` from Jul 1 to Oct 15 inclusive or without date); `AudienceCues` dataclass with `cohorts: set[int]`, `cohort_min: int | None`, `cohort_max: int | None`, `cohort_unresolved: bool`, `degrees: set[str]`, `majors: set[str]`, `programs: set[str]`, `statuses: set[str]`, `excluded_statuses: set[str]`, `all_students, outside_population, unrepresented, condition, absent: bool`, `n_audience, n_condition, audience_chars: int`; `extract_audience_cues(item: ApplicabilityInput, lexicon: Lexicon) -> AudienceCues`.

- [ ] Step 1: Parametrized tests: `"sinh viên K24"` → cohorts `{2024}`; `"khóa 2025"` → `{2025}`; `"từ K22 đến K24"` → min 2022 max 2024; `"K24 về trước"` → max 2024; `"K22 trở đi"` → min 2022; study year with `2025-10-16`: `"năm thứ nhất"` → `{2025}`, `"năm thứ hai trở đi"` → max 2024; `2025-08-01` → unresolved; `test_study_year_without_reference_date_is_unresolved`; `"học viên sau đại học"` → `{master, doctoral}`; `"trừ sinh viên bảo lưu"` → excluded `{on_leave}`; `"chất lượng cao"` → programs `{CLC}`; `"lớp trưởng"` → unrepresented; `"giảng viên"` only → outside_population; no audience text → absent; `none` source reads `event_text`.
- [ ] Step 2: Run; fail.
- [ ] Step 3: Implement with regular expressions over NFC casefolded text.
- [ ] Step 4: Pass.
- [ ] Step 5: Commit `feat: extract audience cues for applicability`.

### Task 4: Feature builder

**Files:** Modify `src/modeling/applicability_features.py`; test same file.

**Interfaces:**
- Produces: `cross_features(cues: AudienceCues, item: ApplicabilityInput) -> dict[str, float]`; `FeatureBuilder(lexicon: Lexicon, *, tfidf: bool = True, source_feature: bool = True)` with `.fit(items) -> FeatureBuilder`, `.transform(items) -> scipy.sparse.csr_matrix`, `.feature_names: list[str]`, `.tfidf_state() -> dict | None` (vocabulary and idf as JSON-safe values).

- [ ] Step 1: Tests `test_cohort_match_conflict_and_range` (profile 2023 vs cohorts {2024}: conflict 1, distance 1; vs bounds 2022–2024: in_range 1), `test_missing_profile_marks_required_unknown`, `test_excluded_status_hit`, `test_raw_profile_values_not_features` (no feature name contains `CNTT` or `2024`), `test_tfidf_fits_training_events_only` (token only in transform set absent from vocabulary), `test_source_feature_toggle`.
- [ ] Step 2: Run; fail.
- [ ] Step 3: Implement; TF-IDF fits on distinct `(doc_id, event_id)` texts.
- [ ] Step 4: Pass.
- [ ] Step 5: Commit `feat: assemble applicability feature matrix`.

### Task 5: Training harness

**Files:**
- Create: `src/modeling/applicability_training.py`
- Test: `tests/test_applicability_training.py`

**Interfaces:**
- Consumes: Task 2–4 names.
- Produces: `TrainingConfig` (Pydantic) with `audience_source, train_sources: list[Literal["email","web"]] = ["email","web"], learning_curve: list[float] | None, seeds: list[int] = [42,43,44], folds: int = 5, tfidf: bool = True, source_feature: bool = True, weighting: Literal["event","pair"] = "event", params: dict, param_grid: list[dict] | None, fit_final: bool = False, allow_synthetic: bool = False`; `load_pool(pairs, assignments, *, allow_synthetic) -> tuple[list[dict], str | None]` (rows annotated with `split`, `group_id`; returns policy); `assign_folds(group_ids: list[str], folds: int, seed: int) -> dict[str, int]`; `web_group_subsets(groups: list[str], fractions: list[float], seed: int) -> dict[float, set[str]]` (nested); `compute_metrics(gold, pred, weights) -> dict`; `run_training(config, *, pairs_path, notices_path, assignments_path, annotations_path, lexicon_path, output_dir) -> Path`.

- [ ] Step 1: Tests: `test_test_split_pair_stops`, `test_unassigned_pair_stops`, `test_mixed_policy_stops`, `test_synthetic_excluded_by_default`, `test_groups_stay_in_one_fold`, `test_folds_independent_of_train_sources`, `test_learning_curve_subsets_nested`, `test_empty_training_fold_stops`, `test_metrics_with_absent_class`, `test_event_weighting_sums_to_one_per_event`, `test_same_seed_same_predictions`, `test_existing_run_dir_refused`, `test_run_writes_complete_record` (files `record.json, folds.jsonl, oof_predictions.jsonl, metrics.json, feature_names.json, importances.json`; record keys include `uv_lock_sha256`, `lexicon_sha256`, `audience_policy`, `train_sources`; metrics carry `label_origin == "constraint_rule"`, per-source and `profile_dependent` sections, majority baseline).
- [ ] Step 2: Run; fail.
- [ ] Step 3: Implement. Run ID `YYYYMMDDTHHMMSSZ-<8 hex of config hash>`. Each experiment key (`mix=<sources>`, `fraction=<f>`) gets its own metrics block. Selection over `param_grid` by mean OOF event-weighted macro-F1 on the first experiment; record `selection_score_is_not_held_out: true`. `fit_final` writes `model.txt` and `tfidf.json`.
- [ ] Step 4: Pass.
- [ ] Step 5: Commit `feat: add GroupKFold LightGBM applicability harness`.

### Task 6: CLI and documentation

**Files:** Modify `src/cli.py`, `docs/interface.md`, `README.md`, `AGENTS.md`; test `tests/test_applicability_training.py::test_cli_train_applicability`.

**Interfaces:** CLI `train-applicability` options exactly as in the spec plus `--lexicon`, `--allow-synthetic`, `--param-grid`.

- [ ] Step 1: CLI test on fixture writes a run directory and prints its path.
- [ ] Step 2: Run; fail.
- [ ] Step 3: Implement; lazy import of the harness inside the command branch. Docs: interface.md "Train applicability features" section (allowlist, run files), README command, AGENTS owner row.
- [ ] Step 4: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv lock --check`, `uv run smartnotice demo`, `uv build` (wheel contains `smartnotice/modeling/`), `git diff --check`.
- [ ] Step 5: Commit `feat: expose train-applicability command`.
