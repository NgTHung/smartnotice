# Implementation plan, 2026-10-20

The proposed folder structure supports the data milestone. This plan separates its executable foundation from the research and application deliverables that require a collected and annotated corpus.

## Data milestone

The foundation covers explicit web URL and local email collection, parsing, normalization, privacy filtering, sentence offsets, Label Studio span/relation exchange, canonical annotation validation, constraint-based applicability pairs, grouped split assignments, and three analysis notebooks. Synthetic fixtures exercise this path without making claims about real source coverage or human labeling quality.

The team needs to choose institutions and notice URLs, collect consented email, record publication dates, run the annotation pilot, review privacy filtering, annotate independently, adjudicate labels, and freeze the research corpus. Pilot measurements determine whether rare optional argument types remain in scope. Record evidence against the targets in [assignment.md](assignment.md).

## Training milestone

Add candidate generation and training/evaluation code after reviewing the pilot schema. Implement the model comparisons and measurement protocol in [evaluation.md](evaluation.md). Include model checkpoints, dataset versions, grouped folds, repeated-seed metrics, domain-transfer experiments, and an extraction-to-applicability error analysis.

No trained model, model-quality measurement, or human agreement result is supplied by the synthetic data workflow. Model capabilities and deployment feasibility need source verification before selecting checkpoints.

## Application and submission

Add the FastAPI service and web UI around the selected models. Preserve evidence highlighting, editable predictions, confidence handling, and session-only input/profile processing. Implement calendar export, deploy to a public cloud, verify the public interaction, and prepare the source ZIP, weights, slides, and PDF report.

Add team identity, repository/submission links, ownership, and course calendar dates when supplied. The source documents state course weeks rather than calendar deadlines.
