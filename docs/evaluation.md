# Produce evaluation evidence

SmartNotice has an extraction task and an applicability task, so evaluation must distinguish direct errors from errors propagated through extracted audiences. This protocol defines evidence for model comparisons without setting an unsupported target F1.

## Freeze data

Use the reviewed grouped split assignments defined in the [data contract](interface.md). Train and tune on the ordinary train/validation pool, retain the ordinary test set, and reserve the web domain test set. Use GroupKFold within training data and repeat runs across recorded seeds. Keep document groups intact in every fold and inherit assignments for every event/profile pair.

Fit TF-IDF, feature selection, preprocessing statistics, hyperparameters, and calibration using training or validation data only. Exclude synthetic demo notices from research measurements. Record source balance, excluded groups, missing labels, and the actual number of documents/events/pairs in each split.

## Compare models

The model families and course comparison requirement live in the [requirements summary](assignment.md). For each proposed comparison, record the exact model/checkpoint identity, tokenizer, software versions, parameters, training seed, hardware, time, and checkpoint path. Verify model capabilities and access conditions against their official sources before implementation.

For applicability rules and feature models, run both human-annotated and predicted audience inputs. For domain transfer, train on email and evaluate on reserved web data, then train with additional non-held-out web data and compare on the same reserved set. Keep all near-duplicate groups out of the training pool.

## Measure extraction

- Exact typed-span precision, recall, and F1, plus per-type counts.
- Argument relation and time-role Macro-F1 with confusion matrices.
- Normalized-date accuracy with separate explicit/inferred/unresolved subsets and stated denominators.
- Event exact match requiring the action, linked arguments, roles, and dates to agree.
- For generated records, unsupported-content rate against source evidence, with an explicit matching rule and manual audit size.

## Compare span candidate filters

Supply a private snapshot with `assignments.jsonl` and `notices.jsonl` and `annotations.jsonl` under each split directory. Each assignment carries the prepared `text_sha256`. Supply a separate [SpanReview ledger](interface.md#validate-candidate-targets). Only reviewed documents contribute supervised targets and metrics. Held-out evaluations require independent or adjudicated annotations. The report lists reviewed and assigned counts so subset results have a clear denominator.

The generator scans time expressions, web URLs, field headings, and Vietnamese phrase cues on the prepared text. It retains overlapping spans and merges only duplicate position–label pairs. Phrase limits come from the 95th percentile of reviewed train spans per label in whitespace-delimited units. Labels without train spans use 12 units. Structural time and URL patterns have their own boundaries. Inspect validation coverage and the limits before freezing an experiment.

Both classifiers use the same candidates and combined sparse features. Character TF-IDF encodes the candidate and up to 100 characters of context on each side. Shared and label-specific text columns let Logistic Regression learn different weights for a phrase under different proposed labels. Length, shape, cue, position and rule features complete the combined representation. The run compares keep-all rules, combined Logistic Regression and Random Forest, Logistic Regression with candidate text and label only, and Logistic Regression with context or rule features removed.

GroupKFold uses frozen groups inside train. Each fold fits its own limits and feature vocabulary. The recorded grid selects parameters using mean exact typed-span F1 at threshold 0.5. Runs with insufficient fold support use recorded defaults. Each configuration then chooses its threshold on validation by exact typed-span F1 with recall as the first tie-breaker. Freeze the checkpoint before opening test or domain test. Run additional seeds with separate output directories and aggregate their results over the same reviewed population.

Before filtering, measure exact candidate recall and same-label overlap coverage against all gold spans. After filtering, report binary metrics on generated candidates and exact typed-span metrics against all gold spans. Compare gold missed by generation with generated gold rejected by the filter. Report per-label and per-source denominators. Undefined ratios are null.

## Measure applicability

Report three-way Macro-F1, per-class precision/recall/F1, the confusion matrix, and APPLIES recall. Report exclusion and implicit-audience subsets separately. State whether labels are silver constraint outputs or independent human judgments, and report agreement on an independently reviewed subset.

Fit temperature scaling on validation logits and choose an abstention threshold on validation data. Report calibration and coverage alongside predictive metrics. A low-confidence application prediction needs confirmation or UNCLEAR; do not choose its threshold on test outcomes.

## Record each run

Save run configuration, dependency lock hash, data/split hashes, seed, grouping threshold, task definitions, predictions with document/event IDs, metrics with denominators, and error categories. Report mean and standard deviation across recorded seeds. Keep qualitative examples redacted and trace them to prepared evidence spans.
