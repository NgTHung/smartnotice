# SmartNotice writing guide

SmartNotice contributors explain how Vietnamese notices become traceable documents, annotations, and research evidence. This guide keeps documentation, notebook narratives, Python docstrings, and code comments consistent so readers can run the workflow and assess its claims.

## Start with the reader's problem

Decide which reader question the document answers before writing. Open with two to four sentences that identify the problem, the intended reader, and how the documented component helps. Describe the component's purpose before listing its files or implementation details.

Weak opening:

> This module contains several data processing utilities for the course project.

Useful opening:

> `smartnotice prepare` converts email and HTML snapshots into redacted documents with sentence offsets. Annotators use those documents to connect each event and argument to its supporting text.

## Choose the document type

Each document has one job. Keep plans, procedures, and observations in their respective homes.

| Type and example | Reader question | Content |
|---|---|---|
| Root [README](../README.md) | What does SmartNotice do, and how do I run it? | Purpose, layout, uv setup, working commands, and links to contracts and evidence |
| [Data contract](interface.md) | What can producers and consumers rely on? | Present-tense input/output rules, offsets, provenance, validation, and reasons |
| [Collection](collection.md), [annotation](annotation.md), or [evaluation](evaluation.md) protocol | How do I produce repeatable evidence? | Steps, tools, recorded fields, versions, review requirements, and measurement boundaries |
| [Collaboration protocol](collaboration.md) | How does work reach the shared branch? | Project fields, issue workflow, branch rules, and local verification policy |
| [Dated plan](project-plan-2026-10-20.md) or [validation record](../reports/validation-2026-10-20.md) | What did we intend or observe on a given date? | Date, scope, environment, commands, observations, limitations, and real issue links |
| [Analysis notebooks](../notebooks/) | What does this corpus show? | Dataset identity, reproducible analysis, tables/figures, interpretations, and limitations |
| Scientific report, using the [report outline](../reports/report-outline.md) | How does the evidence answer the research questions? | Methods, measured results, error analysis, citations, and submission material |
| Public Python docstring | How do I call this, and what does it guarantee? | Inputs, returns, units, edge cases, and relevant exceptions |
| GitHub issue or pull request | What work is required, or what behavior does this change deliver? | Acceptance criteria and progress for issues; resulting behavior and validation for pull requests |

Reference documents omit task progress and change history. Protocols define how to obtain results; dated records and research reports contain the observations. The [GitHub Project and issues](collaboration.md) own current task status. Link to them instead of copying status into READMEs or contracts.

## Describe verifiable behavior

Use the present tense for implemented behavior. Inspect the owning code before describing a function, CLI option, file format, model, or application feature. Keep proposals in actual issues and dated plans, and link to them when explaining scope.

| Avoid | Write |
|---|---|
| The parser now handles tables correctly. | `parse_html` converts table rows into header-value lines so date values retain their column context. |
| The system anonymizes every notice. | The privacy filter masks configured identifier patterns and supplied names; each prepared notice requires human privacy review. |
| The demo proves extraction quality. | The synthetic demo checks the data workflow. Model evaluation follows the evaluation protocol. |

Keep temporary phrases such as "now", "still", "yet", "no longer", and "until" out of reference prose. Do not hide a known limitation: describe its observable effect and the caller's required action. Record later measurements in a new dated section or file rather than rewriting an earlier observation.

## Explain reasons and evidence

Explain the constraint, cost, or failure a decision addresses. A reader can inspect the code for the sequence of operations.

Weak: `normalize_and_redact` runs before `segment_sentences`.

Useful: Normalize and redact before segmentation so sentence offsets refer to the text that annotators receive. Changing that text after annotation invalidates its offsets.

Name the evidence behind a quality or performance claim. Include the dataset version, source mix, sample size, split/grouping settings, parameters, seeds, software environment, hardware when relevant, and measurement procedure, or link to a record containing them. The [evaluation protocol](evaluation.md) owns metric definitions and experiment requirements.

Distinguish synthetic software fixtures, rule-derived silver labels, independent human annotations, and model predictions. State which category supports each table or conclusion. Test counts do not measure model quality, and agreement requires independent annotations on aligned decisions. Give metric denominators and separate measured outcomes from collection targets or planned experiments.

## Give each fact one home

Before adding a paragraph, search for the fact and link to its owner if it exists.

| Fact | Owner |
|---|---|
| Course deliverables and proposal targets | [docs/assignment.md](assignment.md) and its linked original PDFs |
| Persisted fields and validation rules | [docs/interface.md](interface.md) and [src/schemas.py](../src/schemas.py) |
| Collection and annotation procedures | [docs/collection.md](collection.md) and [docs/annotation.md](annotation.md) |
| Evaluation methods and experiment provenance | [docs/evaluation.md](evaluation.md) |
| Install, run, and user workflow entry points | [README.md](../README.md), with detailed annotation steps in their protocol |
| Development commands, architecture, and verification scope | [AGENTS.md](../AGENTS.md) |
| Default split seed | `DEFAULT_SEED` in [src/preprocessing/split.py](../src/preprocessing/split.py) |
| Task status, milestones, and collaboration rules | GitHub issues/Project, linked from [docs/collaboration.md](collaboration.md) |
| Dated observations and scientific report structure | [reports/](../reports/) and its [README](../reports/README.md) |

Keep units, thresholds, and labels consistent with their contract. Preserve field names and categorical values such as `doc_id`, `DEADLINE`, and `UNCLEAR` in code formatting. Do not translate serialized labels in examples or silently replace an unknown value with a guess.

## Use structure that helps the task

Use short headings such as "Review source text", "Validate annotations", or "Compare sources". Use prose for reasoning, lists for discrete steps or options, and tables for comparisons across the same attributes. Avoid section headings that merely announce background or conclusions without naming the reader's task.

Show the smallest working example that replaces an explanation. Commands run from the repository root and use `uv` for Python tools. Link to the README's setup sequence instead of duplicating it. Relative Markdown links resolve from the file containing them; command paths resolve from the repository root.

Keep the root README around 120 lines and subsystem READMEs under 60 lines where practical. Move extended procedures into their owning document under `docs/`. Avoid ASCII or Mermaid diagrams and bold or italic in running prose.

## Write short, direct sentences

Use active voice and address the reader as "you". Prefer concrete actions and examples over adjectives about quality. Preserve Vietnamese diacritics in source phrases, labels shown to readers, and examples.

Avoid em dashes, metaphors, filler introductions, emojis, hashtags, and "not only X, but also Y" constructions. Remove adjectives such as fast, robust, powerful, or seamless unless a measurement supports the specific claim.

Avoid these words and their relatives: comprehensive, delve, utilize, harness, realm, tapestry, unlock, revolutionary, groundbreaking, remarkable, pivotal. Keep terminology consistent instead of replacing a technical term with synonyms for variety.

## Document Python behavior

Follow the public API coverage rules in [AGENTS.md](../AGENTS.md). Put a short docstring as the first statement in a public function or class body. State the caller's contract: accepted inputs, return values, units, missing-value behavior, and relevant exceptions. Explain non-obvious keyword arguments or use a minimal call example when needed.

For text APIs, identify which text offsets refer to and their indexing convention. For date helpers, distinguish explicit, inferred, and unresolved values. Link detailed schema rules to their owner instead of reproducing the schema in every docstring.

Inline comments explain why a decision is necessary or how recovery works. Cite the paper section or equation when implementing a specific published method. Remove comments that repeat code, divide sections, promise later cleanup, narrate refactor history, or carry task IDs. Markdown is useful in rendered docstrings; decorative formatting does not belong in plain comments.

## Write reports and notebook interpretations

Scientific reports under `reports/` use Vietnamese prose. Explain English technical terms on first use, retain serialized field/label names, caption and reference every figure or table, define formula variables, and cite source material. Follow the [course requirements](assignment.md) and [report outline](../reports/report-outline.md) for submission structure.

In notebooks, identify the dataset and its synthetic/research status before interpreting outputs. Name axes and units, state the population or subset behind an aggregate, and distinguish a surface-form count from extraction accuracy. Tie conclusions to saved outputs and describe limitations with their practical effect.

Use invented notices or privacy-reviewed text for examples. Keep source notebooks output-free and link to the notebook execution procedure in AGENTS.md. Generated local reports and notebook copies need privacy review before sharing; an ignored file or automatic redaction flag does not establish that its content is safe to publish.

## Review before handing off

1. Does the opening state the reader's problem and the document's purpose?
2. Does each section belong to the chosen document type and its owning topic?
3. Do claims describe inspected behavior or clearly identified plans, with limitations preserved?
4. Do measurements name their dataset, label origin, sample size, and repeatable evidence?
5. Do examples, labels, paths, and commands match the code and use uv where appropriate?
6. Do local links resolve, and does each shared fact link to its owner?
7. Are examples privacy-reviewed and synthetic material identified?
8. Does `git diff --check` pass? For documentation-only changes, validate links and examples without rerunning unrelated runtime tests.
