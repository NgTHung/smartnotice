# Produce evaluation evidence

SmartNotice has an extraction task and an applicability task, so evaluation must distinguish direct errors from errors propagated through extracted audiences. This protocol defines evidence for model comparisons without setting an unsupported target F1.

## Freeze data

Use the reviewed grouped split assignments defined in the [data contract](interface.md). Train and tune on the ordinary train/validation pool, retain the ordinary test set, and reserve the web domain test set. Use GroupKFold within training data and repeat runs across recorded seeds. Keep document groups intact in every fold and inherit assignments for every event/profile pair.

Fit TF-IDF, feature selection, preprocessing statistics, hyperparameters, and calibration using training or validation data only. Exclude synthetic demo notices from research measurements. Record source balance, excluded groups, missing labels, and the actual number of documents/events/pairs in each split.

## Plan Group K-fold from reviewed events

Use the [event grouping procedure](event-grouping.md) to identify notices about the same edition of an event or the same round of work. Preserve the original notice, reminders and directed updates with their evidence. An email with several events can connect several families for evaluation because its entire text is a single model input; this does not merge the event identities themselves.

[Group K-fold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html) evaluates each group once in a validation fold and uses the other groups to fit the model in that iteration. It takes group IDs as input. SmartNotice's allocator orders eligible groups by descending document count and assigns each to the fold with the fewest documents so far. The seed breaks equal-size group ties. This balances document counts approximately; it does not stratify event labels or sources, and exact fold assignments need not match scikit-learn's.

To reproduce the v3.3 development plan using the original review export:

```powershell
uv run python tools/plan_group_folds.py `
  --assignments data/annotations/split_65_15_20_v3_3_2026-11-15/assignments.jsonl `
  --reviewed-assembly reports/generated/automatic-grouping-2026-11-09-final/assembly.json `
  --notes data/annotations/event-grouping-review-2026-11-06/user-notes/notes-2026-11-09-review-3.json `
  --proposed-assembly reports/generated/automatic-grouping-full-2026-11-15/assembly.json `
  --folds 5 --seed 42 --output-dir reports/generated/group-cv-local
```

For fold `i`, use rows with `fold == i` to validate and rows with another non-null fold to fit. Keep the frozen `validation`, `test` and `domain_test` outside these folds. The [fold contract](interface.md#plan-folds-from-reviewed-events) defines exclusion reasons and artifacts. A plan that excludes the training side of a conflict does not resolve whether the frozen holdout is suitable for final evaluation.

Review proposed links that cross a frozen split or more than one CV fold first. Compare the event name, edition or year, event-specific links, and source references to earlier communications. A reminder can repeat the same task; an extension changes a particular field on the earlier task and keeps both values in its history. Leave unclear links for review. Use the reviewed sample as a regression set, and use new independent pairs and difficult negatives to measure candidate recall and pair precision/recall by relation. Keep holdout decisions and source evidence from influencing rule or threshold selection.

Before freezing a successor split, record the reviewed links and any quarantine, keep web holdout components reserved, and check group membership across all splits. Review class and source counts for each fold before fitting. For a single-label task with enough groups per class, compare [StratifiedGroupKFold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html) if the imbalance matters; a document may contain several event labels, so do not replace its annotations with a single label merely to stratify. Preserve the original split as a historical snapshot.

## Fit and test a grouping baseline

Run `tools/run_grouping_model.py train` with `--dataset` pointing to the frozen grouping release and `--output-dir` pointing to a new directory under `reports/generated`. Use `uv run --group models python`. The command fits scikit-learn logistic regression and its scaler inside each fold, saves out-of-fold predictions and refits a JSON model on the entire train set. In each fold, both endpoints must belong to validation for a pair to be scored. Both must belong to training for a pair to be fitted. The [document contract](interface.md#score-pairs-for-shared-event-identity) describes the input records.

Use the separate `evaluate` command with `--reviewed-holdout`, `--test-notices`, `--model-dir`, `--dataset` and a new `--output-dir`. Freeze case selection and source judgments before viewing scores. Report aggregate counts by decision origin and document selection method. Set aside unresolved pairs when computing scores and report their count. Report positive precision, recall and F1, macro-F1 and confusion counts together. A run with assistant judgments can test transfer to those held-out documents. Estimate generalization with independently reviewed pairs and report candidate recall separately from scoring among selected pairs.

Pass `--variant evidence` to train with nearby source cues and the merge policy. The evaluator loads the configured feature version from the checkpoint. The default evaluates test and `--evaluation-split validation` selects validation. When evaluating an automatic merge, count every `UNCLEAR` prediction as withholding the merge and report how many pairs of each reference class went to review. Report results on cases used for error analysis as regression checks. Evaluate changes on a separate source sample before interpreting transfer.

Use `--raw-email-dir data/raw` to compare title recovery, reference recovery and their combination on the same v2 checkpoint and labeled pairs. The combined policy can use a partial title match with corroborating reference evidence. Label close sends with both supplementary notices and unrelated topics. An evaluation with `--evaluation-split train` is a challenge sample from the train partition. The runner checks the saved fitting-pair hash and rejects any challenge pair that shares a frozen group with it. Report this sample separately from validation and test.

Add `--academic-scope` to evaluate the academic-scope policy against the combined follow-up policy on the same pairs. Use `tools/run_grouping_scope_audit.py` with `--notices`, `--assembly`, `--checkpoint`, `--raw-email-dir` and `--output-dir` to score an unlabeled saved candidate batch. Counts of changed predictions describe system behavior. Measure quality with separately labeled pairs. Give reviewers the two source excerpts and comparable routing facts before sharing model scores. Report cases selected because the policies disagree separately from the wider review sample.

Add `--resolve-followup` together with `--raw-email-dir` to compare source-backed reminders, continuations and deadline extensions. Keep the original checkpoint and policy as a baseline. Record correct update labels and correct update directions on the pairs with corresponding reference labels and directions. Run the assembly with and without `--checkpoint` on the same notices and annotation snapshot. Measure how many positive reference pairs reach candidate review, how many share a final group, which reference negatives share a group, and which directed changes the builder applies.

When expanding training from local source review, freeze the candidate IDs before scoring and retain the reviewer kind, decision, rationale and source sentence offsets. Keep uncertain pairs available for review. Exclude them from fitting. Co-assign the endpoints of reviewed positive training pairs when rebuilding CV folds, and check both the original group and the resulting component against diagnostic groups. Keep all original split assignments. Assistant source judgments can expand development data. Report their results separately from user-labeled comparisons and keep reserved test documents out of fitting.

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
