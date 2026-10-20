# SmartNotice

SmartNotice prepares Vietnamese academic notices for extracting tasks, dates, and the students they apply to. The data workflow turns voluntarily supplied email and public web notices into redacted text, evidence spans, and event/profile examples for annotation and analysis.

## Install and run

Run commands from the repository root. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is absent.

```powershell
uv sync --locked --all-groups
uv run smartnotice demo
uv run pytest
uv run ruff check .
uv run python tools/run_notebooks.py
```

The demo reads synthetic Vietnamese notices from `data/raw/examples/`. Its corpus counts exercise the workflow; they do not measure model quality or real collection progress.

Open the three notebooks with:

```powershell
uv run jupyter lab
```

## Prepare your data

Import one email with a non-identifying reference to its consent record:

```powershell
uv run smartnotice collect-email path/to/notice.eml --consent-ref consent-001
```

For websites, supply the notice URL and its body selector. The [collection protocol](docs/collection.md) explains robots rules, publication dates, grouping, and the reserved web holdout.

```powershell
uv run smartnotice collect-web "https://your-university.edu.vn/notice" --selector "article" --reference-date 2026-10-20
uv run smartnotice prepare
uv run smartnotice split
uv run smartnotice quality
uv run smartnotice export-tasks
```

The URL above illustrates the command syntax. Choose a verified public notice and its actual selector before collection. The collector fetches explicit URLs; it does not discover links.

Import the exported tasks and `data/annotations/label_studio.xml` into your Label Studio instance. Follow the [annotation protocol](docs/annotation.md) to convert completed annotations, review date normalization, and derive applicability labels. Raw sources and generated corpus files are excluded from Git. Review redacted text for remaining personal information before sharing it.

## Find the files

| Path | Purpose |
|---|---|
| `data/raw/` | Immutable source bytes and a local collection manifest |
| `data/interim/` | Redacted notices, reference dates, and sentence offsets |
| `data/processed/` | Grouped split assignments and silver applicability pairs |
| `data/annotations/` | Label Studio configuration and canonical annotation examples |
| `src/collectors/` | Consented local email import and robots-aware HTML collection |
| `src/parsers/` | MIME body extraction and HTML table conversion |
| `src/preprocessing/` | Privacy filtering, segmentation, date helpers, and grouped splitting |
| `src/labeling/` | Annotation validation, Label Studio exchange, and audience rules |
| `notebooks/01_data_quality.ipynb` | Missing dates, privacy review, duplicates, and split checks |
| `notebooks/02_eda.ipynb` | Email/web lengths, sentence counts, and date expressions |
| `notebooks/03_label_analysis.ipynb` | Span/role balance, argument distance, and applicability labels |
| `reports/` | Report outline, dated validation, and generated figures |
| `tests/` | Parser, privacy, collector, annotation, and split checks |

The installed Python package is `smartnotice`. The package mapping in `pyproject.toml` lets its subpackages live directly under your proposed `src/` layout.

## Read the contracts and evidence

- [GitHub Project](https://github.com/users/NgTHung/projects/2) and [collaboration workflow](docs/collaboration.md)
- [Data and annotation contract](docs/interface.md)
- [Course requirements](docs/assignment.md) and [original source documents](docs/reference/)
- [Evaluation protocol](docs/evaluation.md)
- [Dated implementation plan](docs/project-plan-2026-10-20.md)
- [Validation record](reports/validation-2026-10-20.md)
- [Writing guide](docs/WRITING_GUIDE.md)

Team names, student IDs, and submission URLs belong in the submission materials. No team identity or public deployment URL is supplied with this workspace.
