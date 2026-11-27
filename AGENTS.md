# SmartNotice

SmartNotice prepares Vietnamese academic notices for extracting tasks, dates, and the students they apply to. Its data workflow turns email and public web pages into redacted documents, event annotations, and applicability examples so the team can produce traceable training and evaluation data.

## Read before changing scope

Read [README.md](README.md) for setup and layout, [docs/assignment.md](docs/assignment.md) for course deliverables, and [docs/interface.md](docs/interface.md) before changing a persisted format or public function. The original proposal and course brief are under `docs/reference/`.

The [dated implementation plan](docs/project-plan-2026-10-20.md) separates the data foundation from training and application work. Check the code before claiming a proposed model, API, interface, or deployment exists. Follow the user's requested scope; do not add an application stack to a data-preparation task.

## Priorities

1. Correctness and traceability. Every annotated argument and event must resolve to the prepared source text. Reject broken offsets and unsupported labels rather than producing plausible output.
2. Privacy. Preserve consent boundaries and human privacy review throughout collection, annotation, reporting, and publication.
3. Reproducibility. Preserve source hashes, dependency locks, group assignments, seeds, and measurement provenance.
4. Maintainability and measured performance. Keep shared rules in their owning modules, and measure a bottleneck before optimizing it.

## Academic integrity

- Cite papers, datasets, checkpoints, and adapted methods. Identify externally adapted code and respect its license. Use machine learning libraries when appropriate and document their role in the method.
- Keep submitted code readable enough for team members to explain at the oral defense. Use terminology from the event and applicability contracts.
- Distinguish synthetic fixtures, rule-derived silver labels, independent human annotations, and model predictions in every reported result.
- Report only measurements produced by a recorded run. Passing tests or a synthetic demo does not establish model quality, human agreement, collection coverage, or anonymity.
- Keep authorship attributable. Human annotation, adjudication, and team review remain human activities; do not claim to complete them on someone's behalf.

## Environment and commands

Run commands from the repository root. `.python-version` selects Python 3.12; `pyproject.toml` and `uv.lock` define the environment. Use `uv` for installation, dependency changes, scripts, notebooks, and tests. Avoid global package installs and machine-specific interpreter paths.

```powershell
uv sync --locked --all-groups
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run smartnotice demo
```

Choose additional checks according to the change:

| Change | Additional verification |
|---|---|
| Parser, privacy filter, annotation, or split behavior | Start with the relevant test file, then run the suite and offline demo |
| Notebook analysis or code used by notebooks | `uv run python tools/run_notebooks.py`; inspect affected tables and saved figures |
| Dependencies | `uv lock --check`; run the checks that exercise the changed dependency |
| Package mapping, build configuration, or distribution contents | `uv build`; inspect the relevant wheel or source archive contents |
| Documentation only | Check examples against code, resolve local links, and run `git diff --check`; runtime tests are unnecessary |

The [root README](README.md) owns collection and annotation commands. The notebook runner uses the uv interpreter and writes executed copies under `reports/generated/demo/notebooks/`; source notebooks stay output-free. Inspect generated figures for clipping, readable labels, and accidental reuse of another plot's axes.

## Architecture and Python rules

The installed package is `smartnotice`, mapped directly to `src/` by setuptools. Import `smartnotice.parsers` and the other package modules; do not add a second `src/smartnotice/` tree or patch `sys.path` to work around the layout.

| Owner | Responsibility |
|---|---|
| `src/cli.py` | Argument handling and command orchestration |
| `src/schemas.py`, `src/io.py` | Persisted record types and UTF-8 JSONL I/O |
| `src/collectors/` | Source acquisition, consent references, and request policy |
| `src/parsers/` | MIME and HTML body extraction |
| `src/preprocessing/` | Normalization, privacy filtering, dates, segmentation, and grouping |
| `src/labeling/` | Annotation validation, Label Studio exchange, audience rules, and agreement helpers |
| `src/modeling/` | Applicability features, grouped LightGBM training, and run records |
| `notebooks/` | Analysis and presentation using package functions |
| `tools/` | Repeatable fixture and notebook utilities |

- Put reusable behavior in the owning package module. Keep the CLI and notebooks as callers rather than separate implementations of schema or labeling rules.
- Extend schemas and the [data contract](docs/interface.md) together when changing accepted input or persisted output. Update callers, validation, and affected fixtures in the same coherent change.
- Use type hints on public functions and Pydantic models at typed record boundaries. Prefer explicit values and exceptions over hidden global state.
- Use `pathlib.Path`, repository-relative paths, and explicit UTF-8 encoding. Keep the project portable across Windows and Linux.
- Raise descriptive errors for invalid input, with a safe record ID or line number where possible. Catch errors at a boundary that can explain or recover from them. Missing optional metadata follows the documented policy; do not hide parser or validation failures with empty output.
- Validate records before replacing persisted outputs. Preserve raw source bytes and provenance when a later stage fails.
- Add a dependency only when existing code or the standard library does not meet the task. Use `uv add` or `uv add --group dev` / `--group notebooks` and include `pyproject.toml` with the regenerated `uv.lock`. Avoid unrelated dependency upgrades.
- Keep files focused on one responsibility. Extract shared logic when it has multiple callers; avoid speculative abstractions, unrelated formatting, and sweeping rewrites mixed with a feature or fix.

## Protect data and evidence

The [collection protocol](docs/collection.md) and [annotation protocol](docs/annotation.md) own the procedures. Preserve these invariants when changing their implementation:

- Collect participant email only with a consent reference. Honor robots rules, redirect checks, request spacing, and response limits for public web pages. Use mocked HTTP for automated collector tests.
- Keep raw bytes immutable. `.gitattributes` preserves example MIME/HTML bytes because their hashes determine document IDs and annotation references. A line-ending conversion can invalidate an entire fixture family.
- Preserve Vietnamese diacritics. Normalize and redact before assigning offsets; `text[start:end]` must equal stored span text. Prepared-text edits require affected annotations to be regenerated or migrated and validated.
- Reference dates come from the email header or verified web publication date. Preserve missing-date and inference flags rather than substituting collection time or inventing a resolved date.
- Keep ambiguous or unrepresented eligibility conditions unresolved under the contract. Do not replace `UNCLEAR` with a guessed positive label.
- Never log or commit participant email, consent records, name lists, personal profiles, credentials, or unreviewed real corpus text. Keep synthetic fixtures marked explicitly and separate from research data.
- Automatic redaction does not complete privacy review. Preserve the review requirement through exports and inspect examples before sharing reports or executed notebooks.
- Keep generated datasets, executed notebooks, figures, environments, checkpoints, and build outputs outside version control unless a task explicitly requires a reviewed artifact. Check `git diff --cached --name-only` before publishing; an ignore rule alone is not evidence that a file is safe.

## Prevent evaluation leakage

Follow [docs/evaluation.md](docs/evaluation.md) for metrics, model comparisons, calibration, and experiment records. Keep threads, templates, duplicates, and their derived event/profile pairs in the same evaluation group. A reserved web group cannot enter training, and event/profile pairs inherit their document's split.

Use an explicit local RNG seeded from `DEFAULT_SEED` in `src/preprocessing/split.py`, or a recorded override, for stochastic work. Persist split assignments and grouping settings. Fit features, tune parameters, and select calibration or abstention settings on the permitted training/validation data, never the test set. Model inputs exclude the constraints and rule provenance that generated silver labels.

For a performance or quality claim, record the corpus/split version, sample counts, parameters, seeds, environment, and measurement procedure. Keep software validation separate from research evidence, and add a dated record rather than rewriting an earlier result.

## Development workflow

1. Inspect the owning module, its callers, and neighboring tests before editing. Identify the observable behavior or document question the change addresses.
2. For a bug fix, add a regression case and observe the relevant failure before implementing the fix. For a feature, test the caller-visible contract and meaningful edge cases. Keep tests under `tests/`; use synthetic, hand-checkable inputs without live network access.
3. Change the smallest coherent set of owners and callers. Split large work at usable boundaries and keep behavior-preserving refactors separate from functional changes where practical.
4. Run the checks appropriate to the change and inspect their actual outputs. Do not add tests that merely restate implementation or rerun unrelated expensive checks after the required verification passes.
5. Review the diff for scope, generated artifacts, personal information, and stale documentation. State what changed, what was checked, and any material limitation in the handoff.

`tools/create_examples.py` regenerates synthetic raw sources and their annotations together. Use it only when intentionally changing fixtures; inspect the source hashes and regenerated labels before accepting the diff. Adding a test case must not silently rewrite existing evidence.

## Documentation and comments

Read the [SmartNotice writing guide](docs/WRITING_GUIDE.md) before editing Markdown, notebook narratives, comments, or docstrings. It owns document types, fact ownership, prose style, examples, evidence claims, Python documentation style, and Vietnamese scientific report conventions.

Document public functions and classes with a docstring as the first statement in their body. State the caller's guarantees, units, edge cases, and relevant exceptions, and keep them consistent with the implementation and data contract. The writing guide owns wording and examples; this file owns development and verification requirements.

## Tracking and Git

Use [GitHub issues and the SmartNotice Project](docs/collaboration.md) for task scope and progress. If a task names an issue, read it before working and preserve its acceptance criteria. Use real issue IDs and team-supplied ownership, and record human reviews only when they occur. The [dated plan](docs/project-plan-2026-10-20.md) records setup intent; verify later state in the code and actual tracking records.

Changes to `main` go through pull requests. The [collaboration workflow](docs/collaboration.md) owns the branch protection policy. This project uses local verification without CI or required status checks; report the relevant checks in each pull request.

When branching or committing, use descriptive task branches and small Conventional Commits such as `fix: preserve table date evidence` or `docs: clarify annotation review`. Reference real issues when supplied. Preserve unrelated user edits and inspect the staged diff before a commit or push.
