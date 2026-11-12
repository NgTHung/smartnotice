# Produce evaluation evidence

SmartNotice has an extraction task and an applicability task, so evaluation must distinguish direct errors from errors propagated through extracted audiences. This protocol defines evidence for model comparisons without setting an unsupported target F1.

## Freeze data

Use the reviewed grouped split assignments defined in the [data contract](interface.md). The [split procedure](data-splitting.md) explains freezing, extensions and independent gold-test preparation. Train and tune on the ordinary train/validation pool, retain the ordinary test set, and reserve the web domain test set. Use GroupKFold within the development pool of train plus validation, fitting every learned transformation and model only on the training portion of each fold. Repeat runs across recorded seeds. Keep document groups intact in every fold and inherit assignments for every event/profile pair.

Accept duplicate groups and complete independent double annotation and adjudication of the reserved test documents before reporting gold-test metrics. Historical assisted labels remain reference material; they do not establish gold status. Keep held-out predictions and historical labels away from independent annotators. Evaluate each final model on test/domain test after selection, and record any earlier exposure that limits a claim of an untouched test set.

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

## Measure applicability

Report three-way Macro-F1, per-class precision/recall/F1, the confusion matrix, and APPLIES recall. Report exclusion and implicit-audience subsets separately. State whether labels are silver constraint outputs or independent human judgments, and report agreement on an independently reviewed subset.

Fit temperature scaling on validation logits and choose an abstention threshold on validation data. Report calibration and coverage alongside predictive metrics. A low-confidence application prediction needs confirmation or UNCLEAR; do not choose its threshold on test outcomes.

## Record each run

Save run configuration, dependency lock hash, data/split hashes, seed, grouping threshold, task definitions, predictions with document/event IDs, metrics with denominators, and error categories. Report mean and standard deviation across recorded seeds. Keep qualitative examples redacted and trace them to prepared evidence spans.
