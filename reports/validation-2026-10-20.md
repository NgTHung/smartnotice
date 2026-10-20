# Data workflow validation, 2026-10-20

This record checks whether the SmartNotice data workflow runs on the local Windows workspace. It uses invented notices to verify software behavior and does not report collected-corpus coverage, human agreement, or model performance.

## Environment

The checks ran in `D:\HCMUS\ML\smartnotice` on Windows with uv 0.11.7, CPython 3.12.13, and pytest 9.1.1. `uv.lock` records the resolved environment; `.python-version` selects Python 3.12. The original proposal, course brief, and writing guide are retained in the repository.

## Commands and observations

| Command | Observation |
|---|---|
| `uv sync --locked --all-groups` | Installs the project, development tools, and notebook dependencies from the lockfile |
| `uv lock --check` | Lockfile matches project dependencies |
| `uv run pytest` | 43 tests passed |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | Source and notebooks match the formatter |
| `uv run smartnotice demo` | Completes parsing, redaction, annotation validation, split assignment, task export, and silver-label generation |
| `uv run python tools/run_notebooks.py` | Executes all three notebooks in fresh kernels using the uv interpreter |
| `uv build` | Builds the source distribution and Python wheel |

The collector checks use mocked HTTP responses. They cover denied robots paths, redirect-destination checks, unavailable robots rules, request spacing, and response-size limits. No real notice website or participant mailbox was collected during validation. The Label Studio converter is checked with representative export JSON; an interactive Label Studio project was not deployed or exercised.

## Synthetic workflow evidence

The example manifest contains nine synthetic notices: four email and five web documents. The prepared records contain 25 sentences, two automatic identifier redactions, and no missing reference dates. All nine documents retain the privacy-review flag.

The grouped assignment contains six train documents, one validation document, one ordinary test document, and one reserved web domain-test document. The quality check reports zero groups crossing these boundaries. These small counts demonstrate allocation behavior rather than statistical suitability.

Five synthetic annotation records describe six events. They include six ACTION, five AUDIENCE, seven TIME, five CHANNEL, three DOCUMENT, and one CONDITION spans. Their TIME links include four DEADLINE, two START, and one EVENT_TIME relations. Five synthetic profiles produce 30 silver event/profile pairs, including UNCLEAR outcomes for missing attributes and an unresolved free-form condition.

The notebooks save executed copies, embedded plot outputs, and six PNG figures under `reports/generated/demo/`. Figure review checks axis labels, separation between plots, and readable layout. Source-byte checksums match `data/raw/examples/checksums.json`; each saved notebook code cell completes without an error output.

## Limits of this evidence

The [dated implementation plan](../docs/project-plan-2026-10-20.md) owns the remaining research and application work. This run does not establish anonymity, production website compatibility, annotation agreement, extraction quality, calendar integration, or a public cloud deployment. Manual privacy/source review and real corpus collection are required before research annotation and evaluation.
