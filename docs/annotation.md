# Annotate events and audiences

Annotators connect each task to its arguments and evidence so predictions can be audited at event level. Label Studio collects spans and relations; canonical JSONL adds reviewed dates and audience constraints for downstream applicability examples.

The [data contract](interface.md) owns schema rules. The [course requirements](assignment.md) own pilot sizes and double-annotation targets.

## Prepare and label

1. Complete privacy review of prepared text before task export. Keep annotator identities pseudonymous.
2. Export tasks with the command in the root README. Create a Label Studio project, paste [`label_studio.xml`](../data/annotations/label_studio.xml) into its labeling configuration, and import the task JSON.
3. Select the smallest complete ACTION and argument phrases. Include explicit exclusions in AUDIENCE or CONDITION. Split interval endpoints into distinct TIME spans.
4. Draw relations from ACTION to argument. Label TIME links START, DEADLINE, or EVENT_TIME. Label other links with their argument type. Reuse argument spans across actions when justified.
5. Export completed annotations as JSON, not predictions. Keep independent annotators' exports separate before adjudication.

## Convert and curate

For model-assisted labeling, follow [Review LLM event suggestions](llm-labeling.md). It covers Gemini/Featherless configuration, privacy approval, prediction export, and `import-reviewed-labels`, which binds a human completion to its original prediction file and writes a review ledger. Use ordinary unlabeled tasks for independent annotation. Keep assisted reviews identified in research evidence.

```powershell
uv run smartnotice import-labels --input data/annotations/label_studio_export.json --output data/annotations/imported.jsonl
uv run smartnotice validate-labels --annotations data/annotations/imported.jsonl
```

The converter checks canonical text, imports typed spans and links, and assigns containing sentences as initial evidence. Review this evidence, add normalized dates with inference flags, and add structured audience constraints in a curated JSONL file. The UI does not collect normalized dates or structured constraints. [`events.jsonl`](../data/annotations/examples/events.jsonl) shows complete synthetic examples.

Use consistent codes such as `K24`, `CNTT`, and `CLC`. Resolve abbreviations from the source context and record adjudication decisions in an annotation log. Set `implicit=true` for an audience inferred from unstated context. The constraint matcher cannot resolve arbitrary Boolean conditions or calendar expressions.

## Generate applicability examples

```powershell
uv run smartnotice build-pairs --annotations data/annotations/adjudicated.jsonl --profiles data/annotations/examples/profiles.jsonl
```

Use one adjudicated annotation per document. Design synthetic profiles to cover matches, attribute mismatches, excluded statuses, and missing attributes. Keep rule provenance for auditing and review a sample of generated labels independently. Preserve document-level split inheritance as required by the contract.

## Measure annotation quality

Measure pilot time per document, span counts, rare argument types, relation distances, and agreement before expanding collection. `annotation_summary`, `span_f1`, and `cohens_kappa` in [`analysis.py`](../src/labeling/analysis.py) provide counts, exact typed-span F1, and kappa on aligned categorical decisions.

Use exact span offsets and types for span F1. Define the same candidate event/profile pairs for both annotators before calculating applicability kappa. Do not compute kappa over unmatched free-form spans or treat overlapping spans as aligned decisions. Report sample sizes, annotator pairing, adjudication rules, and both disagreements and agreements. The synthetic demo contains no human agreement measurements.
