# Report evidence

Reports connect data and experiment claims to repeatable outputs. Keep dated validation records separate from the scientific report outline so a software check cannot be mistaken for a research result.

- `generated/demo/` holds synthetic quality output, Label Studio tasks, notebook exports, and figures. Regenerate it with the commands in the root README.
- `validation-2026-10-20.md` records the verified setup and example workflow.
- [Validation, 2026-11-03](validation-2026-11-03.md) records parser and privacy regression checks.
- [Validation, 2026-11-04](validation-2026-11-04.md) records the preparation handoff to human review and LLM labeling.
- [Cleaning run, 2026-11-04](validation-2026-11-04-cleaning-run.md) records the staged run over the email archives after emoji removal.
- [Name masking, 2026-11-04](validation-2026-11-04-name-masking.md) records the name audit and the staged run after its fixes.
- [Preprocessing run, 2026-11-04](validation-2026-11-04-preprocessing-run.md) identifies the staged outputs produced at a named commit.
- [Grouped split, 2026-11-12](split-2026-11-12.md) records the curated v3.1 allocation, separate web holdout, delivery hashes and pending gold/group review.
- `report-outline.md` organizes the Vietnamese course report around the seven required stages.

Local generated outputs are excluded from Git because real datasets can contain personal information. Review figures and examples before adding them to submission materials.
