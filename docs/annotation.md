# Annotate events and audiences

Annotators connect each task to its arguments and evidence so predictions can be audited at event level. Label Studio collects spans and relations; canonical JSONL adds reviewed dates and audience constraints for downstream applicability examples.

The [data contract](interface.md) owns schema rules. The [course requirements](assignment.md) own pilot sizes and double-annotation targets.

## Prepare and label

1. Complete privacy review of prepared text before task export. Keep annotator identities pseudonymous.
2. Export tasks with the command in the root README. Create a Label Studio project, paste [`label_studio.xml`](../data/annotations/label_studio.xml) into its labeling configuration, and import the task JSON.
3. Select the smallest complete ACTION and argument phrases. Include explicit exclusions in AUDIENCE or CONDITION. Split interval endpoints into distinct TIME spans. Apply the AUDIENCE and CONDITION scope rules below.
4. Draw relations from ACTION to argument. Label TIME links START, DEADLINE, or EVENT_TIME. Label other links with their argument type. Reuse argument spans across actions when justified.
5. Export completed annotations as JSON, not predictions. Keep independent annotators' exports separate before adjudication.

## Scope AUDIENCE and CONDITION

AUDIENCE marks the people an event addresses. An office, sender, or contact point such as "phòng đào tạo" is not an audience. Label it CHANNEL when the event uses it for submission or contact; otherwise leave it unlabeled.

CONDITION marks an eligibility requirement that a student must satisfy before the event applies, such as a GPA threshold, a conduct score, a completed registration, or the absence of a disciplinary action. Leave procedural circumstances unlabeled, such as "trong phòng thi", "khi nhận vé", or "nếu không có thẻ sinh viên". Every eligibility CONDITION makes an otherwise matching event/profile pair UNCLEAR, so a procedural phrase labeled CONDITION removes valid APPLIES examples.

Model suggestions can contain office AUDIENCE spans and procedural CONDITION spans. Relabel or remove them during review.

## Convert and curate

For model-assisted labeling, follow [Review LLM event suggestions](llm-labeling.md). It covers Gemini/Featherless configuration, privacy approval, prediction export, and `import-reviewed-labels`, which binds a human completion to its original prediction file and writes a review ledger. Use ordinary unlabeled tasks for independent annotation. Keep assisted reviews identified in research evidence.

```powershell
uv run smartnotice import-labels --input data/annotations/label_studio_export.json --output data/annotations/imported.jsonl
uv run smartnotice validate-labels --annotations data/annotations/imported.jsonl
```

The converter checks canonical text, imports typed spans and links, and assigns containing sentences as initial evidence. Review this evidence, add normalized dates with inference flags, and add structured audience constraints in a curated JSONL file. The UI does not collect normalized dates or structured constraints. [`events.jsonl`](../data/annotations/examples/events.jsonl) shows complete synthetic examples.

Resolve abbreviations from the source context and record adjudication decisions in an annotation log. The constraint matcher cannot resolve arbitrary Boolean conditions or calendar expressions.

## Curate audience constraints

Each AUDIENCE span linked to an event needs one constraint row. The profile population is university learners: undergraduates, master's students, and doctoral students. The institution name does not restrict the audience, so "Sinh viên UEH" and "Sinh viên trường ĐH Khoa học tự nhiên" address the whole population.

Choose the constraint `scope` first.

| `scope` | Use when the audience | Example phrase |
|---|---|---|
| `all_students` | addresses every learner who receives the notice, without an attribute restriction | "Sinh viên", "các bạn sinh viên", "tất cả sinh viên" |
| `listed` | names at least one attribute from the table below, or a requirement marked `unrepresented` | "sinh viên K24 chương trình CLC" |
| `implicit` | depends on context the notice does not state, such as a class or course section | "lớp", "chúng ta" in a class email |
| `outside_population` | addresses people who are not university learners | "học sinh THPT", "phụ huynh", "giảng viên" |

An `all_students` constraint may carry `excluded_statuses`, for example "tất cả sinh viên, trừ sinh viên đã tốt nghiệp". It carries no inclusion attributes. Treat "sinh viên" as `all_students` unless the notice contrasts it with graduate learners; then use `degree_levels`.

Write `listed` attributes in canonical form:

| Field | Value | Source phrase and value |
|---|---|---|
| `degree_levels` | `undergraduate`, `master`, `doctoral` | "học viên cao học" gives `master`; "nghiên cứu sinh" gives `doctoral` |
| `cohorts` | admission years as integers | "K24" gives `[2024]`; "khóa 2025" gives `[2025]` |
| `cohort_min`, `cohort_max` | inclusive admission-year bounds | "K24 về trước" gives `cohort_max=2024`; "từ K22 đến K24" gives `2022` and `2024` |
| `majors`, `programs` | codes from the annotation log | "Công nghệ thông tin" gives `CNTT`; "chất lượng cao" gives `CLC` |
| `statuses`, `excluded_statuses` | status codes below | "sinh viên đang học" gives `statuses=["active"]` |

Use either `cohorts` or the bounds in one constraint. Add a new major or program code to the annotation log before using it, and use the same code in synthetic profiles.

| Status code | Meaning |
|---|---|
| `active` | Đang học |
| `on_leave` | Bảo lưu hoặc tạm nghỉ học |
| `suspended` | Bị đình chỉ học tập |
| `defended` | Đã bảo vệ khóa luận hoặc luận văn, chưa nhận bằng |
| `graduated` | Đã tốt nghiệp |

Convert a year of study with the notice `reference_date`. The academic year starts in September, so its start year `A` equals the reference year from September to December and the previous year from January to August. Year of study `N` corresponds to admission year `A - N + 1`. With a reference date of 2025-10-16, "năm thứ nhất" gives `cohorts=[2025]` and "năm thứ hai trở đi" gives `cohort_max=2024`. If the notice states another academic-year boundary, follow the notice and record the decision in the annotation log.

Set `unrepresented=true` and keep the representable attributes when the audience contains a requirement the profile cannot express:

- a class code or role, such as "lớp 24C01", "lớp trưởng", or "ban cán sự". Do not infer a cohort from a class code unless the notice states it.
- a year of study in a notice without `reference_date`, or "năm cuối", whose admission year depends on program length.
- an exclusion of anything other than a status, such as "trừ sinh viên CLC".

## Generate applicability examples

```powershell
uv run smartnotice build-pairs --annotations data/annotations/adjudicated.jsonl --profiles data/annotations/examples/profiles.jsonl
```

Use one adjudicated annotation per document. Design synthetic profiles to cover matches, attribute mismatches, excluded statuses, and missing attributes. Profiles use the same canonical values as constraints: admission year, degree level, logged major and program codes, and status codes. Keep rule provenance for auditing and review a sample of generated labels independently. Preserve document-level split inheritance as required by the contract.

## Measure annotation quality

Measure pilot time per document, span counts, rare argument types, relation distances, and agreement before expanding collection. `annotation_summary`, `span_f1`, and `cohens_kappa` in [`analysis.py`](../src/labeling/analysis.py) provide counts, exact typed-span F1, and kappa on aligned categorical decisions.

Use exact span offsets and types for span F1. Define the same candidate event/profile pairs for both annotators before calculating applicability kappa. Do not compute kappa over unmatched free-form spans or treat overlapping spans as aligned decisions. Report sample sizes, annotator pairing, adjudication rules, and both disagreements and agreements. The synthetic demo contains no human agreement measurements.
