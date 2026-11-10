# Annotate events and audiences

Annotators connect each task to its arguments and evidence so predictions can be audited at event level. Label Studio collects spans and relations; canonical JSONL adds reviewed dates and audience constraints for downstream applicability examples.

The [data contract](interface.md) owns schema rules. The [course requirements](assignment.md) own pilot sizes and double-annotation targets.

## Prepare and label

1. Complete privacy review of prepared text before task export, using `privacy-review-queue` as described in the root README. Keep annotator identities pseudonymous.
2. Export tasks with the command in the root README. It holds back real notices without a matching clearance record and reports how many. Create a Label Studio project, paste [`label_studio.xml`](../data/annotations/label_studio.xml) into its labeling configuration, and import the task JSON.
3. Select the smallest complete ACTION and argument phrases. Include explicit exclusions in AUDIENCE or CONDITION. Split interval endpoints into distinct TIME spans. Apply the AUDIENCE and CONDITION scope rules below.
4. Draw relations from ACTION to argument. Label TIME links START, DEADLINE, or EVENT_TIME. Label other links with their argument type. Reuse argument spans across actions when justified.
5. Export completed annotations as JSON, not predictions. Keep independent annotators' exports separate before adjudication.

## Scope AUDIENCE and CONDITION

AUDIENCE marks the people an event addresses. An office, sender, or contact point such as "phòng đào tạo" is not an audience. Label it CHANNEL when the event uses it for submission or contact; otherwise leave it unlabeled.

CONDITION marks an eligibility requirement that a student must satisfy before the event applies, such as a GPA threshold, a conduct score, a completed registration, or the absence of a disciplinary action. Leave procedural circumstances unlabeled, such as "trong phòng thi", "khi nhận vé", or "nếu không có thẻ sinh viên". Every eligibility CONDITION makes an otherwise matching event/profile pair UNCLEAR, so a procedural phrase labeled CONDITION removes valid APPLIES examples.

Model suggestions can contain office AUDIENCE spans and procedural CONDITION spans. Relabel or remove them during review.

Time normalization must not read durations, clock ranges, lesson periods, or interval fragments as day/month dates. For example, `2-3 ngày`, `9:30-11:30`, and `10-12/11/2026` are not single-date spans. Two calendar dates, including compact endpoints such as `01 - 13/03/2025`, stay unresolved until split and linked with the appropriate roles. A clock range on one stated date does not prevent normalizing that date. A single deadline such as "từ nay đến hết ngày 05/08/2026" and an unambiguous full date such as `05-08-2026` may also be normalized. Keep the original span and role; date normalization does not invent missing endpoints.

Check a CONDITION against its linked ACTION before removing it as procedural. A stated housing need, a required skill or interest, completed registration before collecting a ticket, or a decision not yet collected can determine who qualifies for the action. Keep a source-supported prior-state or eligibility requirement even when the action is part of a procedure. Retain uncertain cases with a context-review flag instead of deciding their applicability from an incomplete phrase.

Project team sizes, supervisor quotas and responsibility assignments describe how to carry out a task. Instructions to watch teaching material or finish a lesson before the next step describe task order. Leave these procedural details unlabeled as CONDITION unless the notice separately establishes a qualification for the audience.

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

If a run explicitly adopts the university-learner population as its default, record that assumption and its version in the annotation log. Under that policy, generic pronouns such as "các bạn" or "em" and mixed audiences including university learners may use `all_students`. An absent AUDIENCE remains absent in the source annotation; use the explicit `--assume-all-students-without-audience` pair-generation option instead of inventing a span. Keep stated degree, cohort, program, status, class and eligibility restrictions, as well as explicit outside-population audiences. Report assumed population coverage separately from source-extracted coverage. Without a recorded population default, context-dependent audiences follow the `implicit` rule above.

The population default does not erase a class, group, volunteer role, supporter role or residence requirement. Synthetic examples such as "Lớp: XYZ_01", "thành viên nhóm XYZ" and "sinh viên cư trú tại khu nhà XYZ" need `listed` with `unrepresented=true` when profiles cannot express the group. A teacher mentioned as teaching a class does not make the addressed students `outside_population`. Flag broad civic groups such as voters or adult residents for human review rather than assuming they are the university-learner population.

In notices using graduate-learner terminology, map "học viên", "HVCH", and "học viên sau đại học" to `master`, and "NCS" to `doctoral`. Mixed lists must include every named learner degree; do not silently omit master's learners from a list that also names undergraduate and doctoral students. A list covering all three degrees addresses the complete learner population.

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

Resolve a relative year of study using these tiers, recording the evidence and policy version:

1. The notice's own evidence wins. Use a stated cohort directly only when it shares the audience's sentence or list item. A cohort in another group's deadline or instruction cannot anchor the audience. Otherwise, use the notice's academic-year start `A` with `cohort = A - N + 1`. Recover complete cohort ranges and comparison words from the prepared source when annotations split or truncate them. New-intake cues such as "tân sinh viên", "nhập học", "đầu năm học" or "tuần sinh hoạt công dân" may anchor the academic year with a verified reference date. For the recorded intake policy, July–December points to the intake beginning that calendar year; January–June points to the preceding academic-year start. An explicit source year overrides this rule. "Nhập học lại" is not a new-intake cue. Missing or conflicting evidence stays unresolved.
2. Without a source anchor, abstain when `reference_date` falls from July 1 through October 15, inclusive. Set `unrepresented=true` and omit cohort values and bounds.
3. Outside that window, use the September boundary: January–June uses the preceding calendar year as `A`; October 16–December uses the reference year. With `reference_date=2025-10-16`, "năm thứ nhất" gives `cohorts=[2025]` and "năm thứ hai trở đi" gives `cohort_max=2024`.

A class code never supplies an admission year by itself. If evidence is split between "khóa từ 24 đến" and "khóa 22", normalize both from the complete source range to `cohort_min=2022, cohort_max=2024`; do not intersect the endpoint as a separate one-year requirement. Record any academic-year override and additional source offsets in the annotation log.

Set `unrepresented=true` and keep the representable attributes when the audience contains a requirement the profile cannot express:

- a class code or role, such as "lớp 24C01", "lớp trưởng", or "ban cán sự". Do not infer a cohort from a class code unless the notice states it.
- a year of study in a notice without `reference_date`, or "năm cuối", whose admission year depends on program length.
- an exclusion of anything other than a status, such as "trừ sinh viên CLC".

## Generate applicability examples

```powershell
uv run smartnotice generate-profiles --annotations data/annotations/adjudicated.jsonl --output data/processed/profiles.jsonl
uv run smartnotice build-pairs --annotations data/annotations/adjudicated.jsonl --profiles data/processed/profiles.jsonl
```

Use one adjudicated annotation per document. `generate-profiles` designs synthetic profiles from the `listed` and `all_students` constraints. For each constraint it adds a matching profile and, for each requirement, a known mismatch and a profile missing that attribute. Each excluded status adds an excluded profile. A requirement gets no mismatch profile when the constraints contain no other value for that major or program. Values come only from the constraints, with the neighbouring admission years added, so profiles never introduce an unlogged code. The command uses `DEFAULT_SEED` unless you pass `--seed`, and it writes `profiles.record.json` next to the output with the seed, the annotation hash, counts, and `profile_set_sha256`. Keep rule provenance for auditing and review a sample of generated labels independently. Preserve document-level split inheritance as required by the contract.

## Measure annotation quality

Measure pilot time per document, span counts, rare argument types, relation distances, and agreement before expanding collection. `annotation_summary`, `span_f1`, and `cohens_kappa` in [`analysis.py`](../src/labeling/analysis.py) provide counts, exact typed-span F1, and kappa on aligned categorical decisions.

Use exact span offsets and types for span F1. Define the same candidate event/profile pairs for both annotators before calculating applicability kappa. Do not compute kappa over unmatched free-form spans or treat overlapping spans as aligned decisions. Report sample sizes, annotator pairing, adjudication rules, and both disagreements and agreements. The synthetic demo contains no human agreement measurements.
