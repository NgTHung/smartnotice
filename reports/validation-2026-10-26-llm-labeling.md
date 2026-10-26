# LLM labeling software validation, 2026-10-26

The labeling workflow was checked on Windows with Python 3.12.12, httpx 0.28.1, and Pydantic 2.14.1 using the locked uv environment. This record covers software behavior and synthetic provider access. No participant notices were sent and no human annotation or adjudication was performed during this check.

## Local verification

| Command | Observed result |
|---|---|
| `uv run pytest` | 67 passed, including 24 LLM labeling tests |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | 55 files already formatted |
| `uv run smartnotice demo` | Nine synthetic notices; original workflow completed |
| `git diff --check` | Passed |
| Local Markdown link checks | Changed documentation links resolve |
| `git diff --cached --name-only` | No staged files |

The feature tests cover quote-to-offset conversion, shared arguments, repeated phrases, invalid labels/links, privacy approval preflight, mocked provider responses, safe failures, partial batch output, configuration loading, accepted/edited/skipped reviews, stale originals, missing reviewers, empty exports, and CLI round trips. Simulated human exports exist only in test fixtures and temporary directories.

## Live synthetic requests

Both providers used document `0d497e6fefde3daed7eb` from `data/interim/demo/notices.jsonl`. Its raw SHA-256 is `0d497e6fefde3daed7ebd0ace648c13e974649d72f08e84853b9f35c11ea54a2`; its prepared-text SHA-256 is `6a7b2cc3e02817cd75ae8986125732e40058ca5548a91227e70bca67d464012d`.

| Provider and configured model | Observed result |
|---|---|
| Featherless, `zai-org/GLM-5.3-Flash` | One valid prediction with five spans and one event; empty failure ledger |
| Gemini, `gemini-3.8-flash` | First attempt returned HTTP 503; one explicit retry failed on the connection; zero valid predictions |

The Featherless artifact's prepared text, offsets, typed relations, and prediction hash were checked against the source Notice. Gemini's mocked adapter tests passed; a successful live extraction from the configured Gemini model remains unverified.

Ignored local artifacts are under `reports/generated/llm-smoke-2026-10-26/`. `verification.json` records the environment, dependency-lock hash, artifact hashes, and per-attempt results. Original tasks and failure ledgers preserve the three live attempts. The successful review task is `featherless.tasks.json`.

## Complete human verification

Import the successful task into Label Studio using the existing XML configuration, check the displayed spans and relation arrows, submit a human annotation, and export standard JSON. Then run `import-reviewed-labels` with the original task file and validate the resulting annotations as described in the [pipeline procedure](../docs/llm-labeling.md).

Label Studio display, browser offset handling, real human review, privacy clearance of research data, independent agreement, and model quality were not measured by this software run. The live result is a synthetic smoke test rather than an extraction-quality evaluation.
