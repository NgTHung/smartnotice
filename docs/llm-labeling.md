# Review LLM event suggestions

Gemini and Featherless can suggest event spans from prepared notices so annotators can check and correct them in Label Studio. This procedure takes a prepared Notice corpus through model suggestions, human completion, and validated annotation import. Keep the original prediction file alongside each human export to preserve the review trail.

## Follow the pipeline

1. Prepare normalized, redacted notices with stable sentences and source hashes.
2. Record privacy clearance and permission to send each real notice to the chosen provider. Synthetic fixtures bypass this approval record.
3. Send the reference date and prepared sentence text to Gemini or Featherless. The prompt includes the draft schema and identifies notice content as untrusted data.
4. Ask the model to quote exact substrings within sentence IDs. Python resolves the quotes to canonical offsets; repeated quotes need an explicit occurrence number.
5. Validate spans, ACTION-to-argument links, time roles, and evidence. Write valid suggestions as Label Studio predictions and failed attempts as a separate JSONL ledger.
6. Have a person check the predictions, create an annotation, correct errors, and submit it in Label Studio.
7. Import the completed export against the original prediction file. Validate the edited annotation and record its accepted, edited, or skipped decision.
8. Curate dates, evidence, and audience constraints, adjudicate independent annotations, and derive applicability pairs under the [annotation protocol](annotation.md).

The [data contract](interface.md) owns persisted fields and offset rules. Model suggestions, assisted human annotations, independent human annotations, and rule-derived pairs have different origins. A submitted Label Studio completion records a review action; it does not independently establish annotation quality or adjudication.

## Configure providers

Run from the repository root after the installation steps in the [README](../README.md). The labeling CLI reads these four names from the local `.env` file:

```dotenv
GEMINI_MODEL=your-gemini-model-id
GEMINI_KEY=your-gemini-api-key
FEATHERLESS_MODEL=your-featherless-model-id
FEATHERLESS_KEY=your-featherless-api-key
```

Existing process environment values take precedence over `.env`. The loader accepts simple `KEY=value` lines, optional matching single or double quotes, and unquoted inline comments introduced by a space and `#`. It performs no variable interpolation. Keep credentials in the ignored `.env` file or process environment.

`--model` overrides the corresponding model variable for one command. Requests use temperature 0, an 8,192-token output limit, and a 90-second HTTP timeout. A seed does not establish deterministic hosted inference. Review tasks record the requested model, prompt version/hash, parameters, run ID, UTC time, source hash, prepared-text hash, and prediction hash.

The implementation uses the existing `httpx` dependency with Gemini's [generateContent API](https://ai.google.dev/api/generate-content) and Featherless's [chat completions endpoint](https://featherless.ai/docs/completions). Gemini receives a JSON schema. Featherless receives the same schema in its prompt; the selected model's JSON behavior must be checked in a live smoke test. Both responses pass the same local validator. Refused, empty, truncated, or malformed responses fail.

## Test one synthetic notice

Prepare the existing fixtures without changing their source files:

```powershell
uv run smartnotice demo
```

Preview the selection and configured model without making an API request:

```powershell
uv run smartnotice suggest-labels --notices data/interim/demo/notices.jsonl --doc-id 0d497e6fefde3daed7eb --provider gemini --output data/annotations/smoke-gemini.json --dry-run
```

Call each provider once on that synthetic notice:

```powershell
uv run smartnotice suggest-labels --notices data/interim/demo/notices.jsonl --doc-id 0d497e6fefde3daed7eb --provider gemini --output data/annotations/smoke-gemini.json
uv run smartnotice suggest-labels --notices data/interim/demo/notices.jsonl --doc-id 0d497e6fefde3daed7eb --provider featherless --output data/annotations/smoke-featherless.json
```

Each command creates a JSON task array and a sibling `.errors.jsonl` ledger. For example, `smoke-gemini.json` has `smoke-gemini.errors.jsonl`. A successful single-document run writes one prediction and an empty failure ledger. Existing outputs are refused; use a new filename for another attempt. A nonzero exit code can accompany a partial batch: inspect the success count and failure ledger before retrying failed document IDs.

Omit `--doc-id` to process the full supplied corpus sequentially. Repeat `--doc-id` to select several notices. All selected real documents must pass approval before the first request. There are no automatic retries or silent provider switches. Use `--errors-output` to choose a different failure-ledger path. Failures contain safe document IDs and reasons, never API keys or response bodies.

## Review in Label Studio

1. Create a project in your Label Studio instance. Paste [`label_studio.xml`](../data/annotations/label_studio.xml) into its labeling interface.
2. Import one generated task file. Enable prediction pre-labeling or copy its prediction into a new annotation, according to your Label Studio version. Imported predictions themselves are read-only; see the [prediction guide](https://labelstud.io/guide/predictions).
3. Compare every highlighted quote with the source. Add missed ACTIONs or arguments, remove unsupported spans, and check relation directions and TIME roles. Check documents with zero predicted events for missed tasks.
4. Submit the corrected annotation. Skipping/canceling a task produces no canonical annotation. Keep the original task file unchanged.
5. Export completed tasks as standard JSON, retaining `data.proposal`. Each task in this review import needs exactly one completion with a pseudonymous reviewer ID or Label Studio numeric user ID. Export independent annotators separately.

Import the human export and original predictions together:

```powershell
uv run smartnotice import-reviewed-labels --notices data/interim/demo/notices.jsonl --input data/annotations/label_studio_export.json --predictions data/annotations/smoke-gemini.json --output data/annotations/reviewed.jsonl --review-log data/annotations/reviews.jsonl
uv run smartnotice validate-labels --notices data/interim/demo/notices.jsonl --annotations data/annotations/reviewed.jsonl
```

The importer rejects missing completions, unknown reviewers, changed prepared text, changed run metadata, and altered original predictions. An export may contain a reviewed subset of the original tasks. Review decisions are `accepted` when span/link content and IDs match the original, `edited` when valid content differs, and `skipped` for cancellation. The log stores the reviewer ID, import time, run ID, hashes, source status, and final annotation hash when available. It omits annotator email and account metadata.

Dates and structured audience constraints remain a separate human curation step. The Label Studio interface does not collect them. The model does not propose normalized dates or applicability labels. Follow [Convert and curate](annotation.md#convert-and-curate) before using one adjudicated annotation per document with `build-pairs`. Keep an independent annotation subset free of model suggestions when measuring human agreement, and keep prompt tuning away from held-out test data under the [evaluation protocol](evaluation.md).

## Approve real prepared text

Complete privacy review of the exact text before recording approval. The prepared Notice's `privacy_review_required` flag is not evidence of clearance. Collection consent alone does not establish permission to transfer text to an external model provider.

Create a private UTF-8 JSONL file at `data/annotations/provider_approvals.jsonl`, or pass another path with `--approvals`. Each row follows this shape; replace the placeholders only after actual human review:

```json
{"doc_id":"<prepared-doc-id>","text_sha256":"<64-character-sha256>","reviewer_id":"reviewer-1","reviewed_at":"<actual-time-with-timezone>","providers":["gemini","featherless"],"privacy_cleared":true,"provider_use_approved":true}
```

Compute the digest with `hashlib.sha256(notice.text.encode("utf-8")).hexdigest()`, or use `text_sha256` from `smartnotice.labeling.llm`. Approval requires the exact document ID, text hash, named provider, both true flags, a nonempty reviewer ID, and a timezone-aware review time that is not in the future. A prepared-text edit invalidates that approval and all affected offsets. Keep approval and consent records out of Git.

## Check software behavior

The regression tests mock provider HTTP and simulate annotation exports with synthetic fixtures. They check exact quote resolution, Vietnamese/emoji offsets in Python, repeated phrases, invalid labels and links, approval boundaries, partial batch failures, safe errors, environment loading, original-file checks, human edits, skipped tasks, CLI outputs, and refusal to overwrite evidence.

```powershell
uv run pytest tests/test_llm_labeling.py tests/test_labeling.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run smartnotice demo
git diff --check
```

Run a small live synthetic request separately to verify model access and actual JSON behavior. Inspect the Label Studio display and submit a real human completion before claiming UI review verification. Browser non-BMP offsets may differ from Python indexing; the import validator rejects mismatched spans. Tests and live smoke requests establish software behavior, not extraction quality, anonymity, or human agreement.

HTTP 401/403 indicates an access problem; 429 indicates throttling; 5xx indicates provider failure. A quote/schema error means the response could not satisfy the local evidence contract. Preserve the failure ledger, check provider access or label the notice manually, and retry deliberately into new output files.
