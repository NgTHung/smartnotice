# Implement the SmartNotice BamiBERT pipeline

This plan guides SmartNotice contributors from prepared notices to evidence spans, linked events, and student applicability predictions. The extraction model uses one BamiBERT encoder with a span head and a relation head. A second BamiBERT instance classifies each extracted event against a student profile. The existing repository supplies the preparation, annotation, split, date, and silver-label components. The training and inference steps below describe the proposed implementation.

## Pin the inputs

Use the setup in the [README](../README.md). Use Python 3.12 and add PyTorch, Transformers, and scikit-learn to a uv training dependency group. Add PEFT when running LoRA and LightGBM when implementing that comparison. Select the PyTorch build for the training device and lock the environment with uv. Use the model card's documented Transformers range (at most 5.5.0), then smoke test the exact locked versions. Pin the BamiBERT repository revision and use it for both `AutoTokenizer.from_pretrained(..., use_fast=True, revision=...)` and `AutoModel.from_pretrained(..., revision=...)`. Verify the tokenizer is fast and returns usable offset mappings. BamiBERT is a Vietnamese RoBERTa encoder with a 2,048-token limit and its own tokenizer. Review the model card terms before distributing weights or deploying a service. [BamiBERT model card](https://huggingface.co/Qualcomm-AI-Research/BamiBERT), [BamiBERT paper](https://arxiv.org/abs/2607.02259).

Use the v2 frozen release from the [split run](../reports/split-2026-11-12.md), which records 317 train, 73 validation, 99 ordinary test, and 45 web domain-test documents. Publish the counts from the actual run inputs. Join every notice, window, span, relation, and event/profile pair to `assignments.jsonl` by `doc_id` and inherit its `group_id` and split. Verify source and prepared-text hashes and the invariants in the [split procedure](data-splitting.md). Hold out `test`, `domain_test`, and `excluded` from all fitting, threshold selection, and rule development.

Load `Notice`, `Annotation`, and `Profile` through the [existing schemas](../src/schemas.py) and [JSONL I/O](../src/io.py). Run `validate_annotation` before transforming a labeled document. Distinguish a completed empty annotation from a missing annotation. An unannotated notice provides no negative training examples. Within the training pool, track label origin and the support of each span, relation, and applicability class. Synthetic notice fixtures are for software checks. Synthetic profiles paired with real notices can supply silver training examples.

Generate the profile bank from training annotations or define it in advance using the schema. Freeze it before scoring validation and test. The existing CLI derives the silver label from the canonical event and its reviewed constraints. For example, with the v2 release in `data/processed/`, these commands prepare train and validation pairs from a single training-derived profile bank.

```powershell
$SplitRoot = 'data/processed/split-v3_1-2026-11-12-v2'
$PairRoot = 'data/processed/bamibert-v2'
New-Item -ItemType Directory -Path $PairRoot -Force | Out-Null
$Profiles = "$PairRoot/train-profiles.jsonl"
uv run smartnotice generate-profiles --annotations "$SplitRoot/train/annotations.jsonl" --output $Profiles
if ($LASTEXITCODE -ne 0) { throw 'Profile generation failed' }
foreach ($Part in @('train', 'validation')) {
    uv run smartnotice validate-labels --notices "$SplitRoot/$Part/notices.jsonl" --annotations "$SplitRoot/$Part/annotations.jsonl"
    if ($LASTEXITCODE -ne 0) { throw "Invalid annotations in $Part" }
    uv run smartnotice build-pairs --notices "$SplitRoot/$Part/notices.jsonl" --annotations "$SplitRoot/$Part/annotations.jsonl" --profiles $Profiles --output "$PairRoot/$Part-applicability.jsonl"
    if ($LASTEXITCODE -ne 0) { throw "Pair generation failed for $Part" }
}
```

During grouped cross-validation, rebuild profiles and derived training examples inside each fold from its fitting partition. Keep the default missing-audience policy (`UNCLEAR`) for the first run. Any later policy change needs its own label configuration and run. For final applicability evaluation, define a fixed set of event/profile pairs and have people judge them independently from the source and profile. Preserve both judgments and adjudicate disagreements. See the [annotation protocol](annotation.md).

## Build the span extractor

1. Tokenize `Notice.text` directly with the pinned tokenizer. Preserve Vietnamese diacritics, whitespace, and the prepared text used by the annotation. Use tokenizer overflow and offset mappings to create overlapping windows with document-level offsets. Start with 512 tokens including special tokens and 128 tokens of overlap as a pilot setting. Compare 1,024 tokens on development data if window coverage is poor. Dynamic padding keeps short notices cheap.
2. In each window, enumerate contiguous spans of up to `W` non-special, non-padding tokens. Keep valid character boundaries within a source sentence so selected spans can resolve to evidence. Start `W` at the 99th percentile of exactly alignable training-span lengths, rounded up. Report the tail and check representability and per-type candidate recall on development data. Include the right endpoint token when computing the character end. Derive the span text from `Notice.text[start:end]`. Audit repeated offsets from subword tokens and map duplicate character intervals to one candidate before scoring.
3. Match annotations by exact character offsets. Audit spans split at the window boundary, spans wider than `W`, and offsets that the tokenizer cannot represent exactly. Exclude clipped fragments of a gold span from negative sampling. Check for multiple labels at the same boundary before using single-class softmax. If they occur and are valid, use independent span label scores and preserve the distinct typed spans.
4. Represent each span with its first and last token states, mean of its token states, and a learned width embedding. Feed the concatenation to a dropout and MLP classifier with output classes `NONE`, `ACTION`, `TIME`, `AUDIENCE`, `CONDITION`, `CHANNEL`, and `DOCUMENT`. Train with cross-entropy for the single-label case. Retain all representable positives and sample `NONE` examples per document in training. Start with up to five negatives per positive, including near-boundary negatives and a fixed small budget for completed no-event notices. Seed and record the sampler. Score the full configured candidate set at evaluation.
5. When a candidate occurs in multiple windows, assign it to the window with the largest minimum distance to its two real-token edges. Break ties by earlier window. Apply this ownership rule to training examples and inference. Keep one prediction per `(doc_id, start, end, label)`. Choose a non-`NONE` threshold on development data. Retain overlapping distinct spans supported by the model and the contract.

Measure the proportion of gold mentions representable after each limit. A width, window, or pruning rule can lower the maximum possible exact-span recall.

## Train action–argument linking

Generate directed candidates from every retained `ACTION` to every retained non-`ACTION` span in the same document. An argument can serve several actions. Use distance and evidence position as features so a date in a heading or table can link to an action elsewhere.

```text
for each document:
    for each ACTION span a:
        for each non-ACTION span b:
            pair = (a, b)
            if pair is linked in the annotation:
                target = time_role if b is TIME else b.label
            else:
                target = NO_RELATION
```

Build supervised pairs from annotated spans. Keep all positive links and sample training negatives with a seeded budget. Include close but incorrect dates and arguments linked to another action. At evaluation, score every pair emitted by the configured generator. If the document-level product is too large, introduce a recorded cap after measuring candidate counts and validate its effect on relation candidate recall.

Use a pair MLP over the action and argument span vectors, argument type, relative signed distance, and same-sentence indicator. For a pair covered by one window, encode both in the window that maximizes the minimum distance between either span and a real-token window edge. Otherwise use each span's vector from its own window and set a cross-window indicator. Batch windows by document for joint training so the pair loss can backpropagate through both endpoints. This retains cross-window candidates with separately contextualized endpoints. Track their performance separately. If they are a major source of error, test a second pass over both evidence snippets with the action and argument marked.

The relation head has `NO_RELATION`, `START`, `DEADLINE`, `EVENT_TIME`, `AUDIENCE`, `CONDITION`, `CHANNEL`, and `DOCUMENT` outputs. Apply a type mask before softmax. TIME allows the three time roles and `NO_RELATION`. Each other argument type allows its own label and `NO_RELATION`. Use cross-entropy over valid labels. The non-time relation label is represented by the argument's span type in the canonical record. Its persisted `role` stays empty. The relation head predicts a linked role per pair, so a shared TIME span can have different roles across actions.

Train the span head first to check learning and offset reconstruction. Initialize the joint extractor from that checkpoint, then train the shared encoder and both heads with `L = L_span + λ × L_relation`. Compute each mean on its supervised examples. A document with zero eligible pairs contributes zero relation loss. Start with `λ = 1`. Use annotated endpoints for the supervised relation loss and predicted endpoints for end-to-end validation. If the gap is large, try adding predictions from models fitted on other training groups. Transfer a positive link only when both typed offsets match an annotated link, and audit sampling and label noise.

With the synthetic notice `Sinh viên K24 đăng ký học phần trước 20/11 và nộp học phí trước 25/11.`, the pair generator emits four action/date candidates.

| ACTION | TIME | Training label |
|---|---|---|
| đăng ký học phần | 20/11 | `DEADLINE` |
| đăng ký học phần | 25/11 | `NO_RELATION` |
| nộp học phí | 20/11 | `NO_RELATION` |
| nộp học phí | 25/11 | `DEADLINE` |

The same `Sinh viên K24` span can link to both actions. This design adapts the idea of using predicted spans to construct relation candidates. PURE runs separate entity and relation encoders, while this plan shares the extraction encoder. [Zhong and Chen, NAACL 2021](https://aclanthology.org/2021.naacl-main.5/).

## Decode events and dates

1. Decode the selected ACTION spans and relation decisions. Build one event per retained ACTION with all accepted outgoing links. Drop orphan argument spans from exported events. Preserve raw typed-span predictions separately for span scoring.
2. Take the source sentence containing the action and the sentences containing linked arguments as evidence. Preserve source order and allow the same sentence to support several events. Use document offsets and typed spans for evaluation joins. Generated span and event IDs are local identifiers.
3. Normalize numeric TIME values with [`normalize_date`](../src/preprocessing/dates.py) and the notice's verified `reference_date`. The current helper resolves numeric day/month forms with an explicit year or a reference-year inference. Apply it to supported single-date expressions. Use surrounding context to screen out durations, clock ranges, and fragments such as `10-12` inside a date interval. Relative dates and missing reference years can remain unresolved. Store `normalized_date=null` when unresolved and keep `inferred` from the helper. An interval uses separate endpoint spans. Keep learned roles separate from the deterministic date conversion.
4. Validate against the [data contract](interface.md) and reuse [`validate_annotation`](../src/labeling/validation.py) for shared structure checks through a prediction adapter. Supply no invented audience constraints. Save model provenance and confidence with the prediction, outside the human annotation record. Report validation failures by safe document ID with the reason.

## Train student applicability

Use `AutoModelForSequenceClassification` initialized from the pinned BamiBERT checkpoint with three labels in a fixed mapping. Tokenize a pair consisting of event source context and a stable Vietnamese serialization of the profile. The cross-encoder allows the profile fields to attend to the notice text.

| Input | Construction |
|---|---|
| Event context | Use the sentences supporting the selected action and its linked arguments, in original order. Mark the selected action and optionally its linked AUDIENCE and CONDITION evidence with the same rendering code for annotated and predicted events. Markers are model input only and leave stored offsets unchanged. |
| Profile | Serialize `cohort`, `degree_level`, `major`, `program`, and `status` in a fixed order with a consistent missing-value marker. Exclude `profile_id`. |
| Target | Learn `APPLIES`, `NOT_APPLIES`, and `UNCLEAR` from the pair label. Use ordinary three-class cross-entropy for the first run. |

Join pair rows to the original event and notice by IDs to render the marked context. Read evidence text and profile fields for model inputs. Keep constraints, label origin, rule reasons, policy flags, hashes, and IDs in the audit metadata. Reserve budget for the profile and the marked action, audience, and condition when building the token sequence. Log context omissions and measure performance on long evidence sets.

Count support per class and per event. Cap repeated training profiles per common event if they dominate sampling. Prefer informative variations with a matching profile, a mismatch, an exclusion, and a missing field where those examples exist. Keep the evaluation pair list fixed across methods. Balance weights may be tried using training support only. Record that performance on `constraint_rule` targets measures rule agreement. Estimate real applicability separately with independently judged pairs.

## Fit and compare models

Full fine-tuning updates both BamiBERT encoders in their own training runs and trains the new heads. It is the first main experiment. Try LoRA if the hardware budget limits full training or after a full run to measure the difference. A head-only run freezes the encoder and gives a lower-cost control. The three modes are ablations of BamiBERT.

| Setting | First full run | LoRA comparison |
|---|---|---|
| Optimizer | AdamW, initial weight decay 0.01 and gradient clipping at 1.0 | Same, on adapters and heads |
| Learning rate | Encoder `2e-5`, heads `1e-4`. If the first run is stable, compare encoder rates `1e-5` and `5e-5`. | Adapters and heads `1e-4` as a starting point |
| Adapter settings | All encoder parameters trainable | `r=8`, `lora_alpha=16`, dropout `0.05`, attention `query` and `value`. Verify target module names on the loaded model. |
| Budget | Start with 8 windows or pairs per optimizer step via gradient accumulation, up to 10 epochs, patience 2. Use a 10% warmup followed by linear decay. | Use the same splits, starting sequence budget, and selection metric. Record any hardware-driven differences. |
| Checkpoint selection | Span micro-F1 for the warm start, end-to-end labeled link micro-F1 for joint extraction with exact-event F1 as tie-breaker, and applicability Macro-F1 on annotated event inputs for applicability | Same, with comparable tuning effort |

Tune these pilot settings on development data. The BamiBERT paper supplies the initial range for encoder learning rates. Use mixed precision only when supported by the device, and reduce per-step windows or use gradient checkpointing if memory is tight. For LoRA, keep the heads trainable and save them with the adapter. When PEFT wraps only the encoder, save the custom heads alongside it. When PEFT wraps the entire model, verify the classifier modules are included in `modules_to_save` or recorded separately. Verify trainable-parameter counts and reload the artifact before comparing. [BamiBERT experiments](https://arxiv.org/html/2607.02259v1#S3), [PEFT LoRA reference](https://huggingface.co/docs/peft/en/package_reference/lora).

Use the [course comparison scope](assignment.md) for model families. Evaluate all trained variants with common splits, label definitions, dates, and evidence matching.

| System | Algorithm |
|---|---|
| Rule candidates + Logistic Regression extraction | Generate spans from a training-reviewed cue list and regexes on prepared text. Use candidate text/context TF-IDF and a span classifier to accept, reject, or type them. Form action/argument candidates, then classify their label with Logistic Regression using TF-IDF plus type, signed distance, sentence and cue features. Fit vectorizers only on the fitting partition. |
| Rule candidates + LightGBM extraction | Reuse the same span stage and candidate pairing. Train the relation head with LightGBM on type, distance, sentence position, time cue, and available table or heading cues. Use features available from the prepared notice at inference. [LightGBM paper](https://papers.nips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html) |
| BamiBERT extraction | Enumerate spans and learn both heads as specified above. |
| ViT5 extraction | Train a local text-to-structure encoder-decoder on validated examples. Use deterministic JSON targets with quotes and sentence IDs, plus a repeated-quote occurrence index when needed. Resolve source offsets, validate events before acceptance, and record malformed outputs and unsupported fields. [ViT5 paper](https://aclanthology.org/2022.naacl-srw.18/) |
| Applicability rules and LightGBM | Run [the matcher](../src/labeling/applicability.py) and a learned matching-feature baseline with both annotated and predicted audience inputs. Build features from available source cues and profile fields. Produce predicted constraints through a documented parser for predicted inputs. If a rule baseline uses curated constraints, report that input as an oracle and identify any overlap between the rule and the silver label generator. |
| BamiBERT applicability | Score source context and the profile together. Run on annotated and predicted event inputs using the same renderer. |

For rule candidates, use triggers such as `đăng ký` or `nộp` for ACTION, numeric dates and relative time phrases for TIME, and `sinh viên` or `K24` for AUDIENCE. Use eligibility cues for CONDITION, URLs or submission-place cues for CHANNEL, and form or transcript mentions for DOCUMENT. Emit bounded phrases and alternative exact boundaries as needed. For `trước ngày 20/11`, propose `20/11` as a TIME span and use `trước ngày` as a relation feature. Emit two candidate TIME spans for a range with two explicit endpoints. Match candidates against reviewed training labels and measure validation recall per type before refining the rules.

## Evaluate without using held-out labels for development

1. Start with the frozen train/validation split for the first working run. Use `GroupKFold` within the combined development pool for robustness and comparisons. For each fold, fit widths, rules, profiles, vocabularies, feature transforms, sampling weights, and models on fitting groups only. Use an inner grouped fit/validation split for checkpoint selection and calibration if reporting outer-fold scores as independent estimates. Development scores used for selection should be reported as such.
2. Freeze the selected configuration and variants before evaluating on the ordinary test and reserved web domain test. Use the frozen train partition for fitting and validation for checkpoint and threshold selection. Run the chosen configurations with the same three recorded seed overrides, for example 42, 43, and 44. Report sample mean and standard deviation of the seed results. Keep document assignments fixed across seeds.
3. For domain transfer, compare email-only train/validation against a train/validation run with added non-held-out web documents on the same web test. Use the same scoring code and explain the effect of extra training volume. Report actual source counts and calibration pools. Follow [the evaluation protocol](evaluation.md).

| Evaluation | Scoring procedure |
|---|---|
| Candidate coverage | Divide exact gold span candidates found by all gold spans. Divide gold links for which both endpoints and the directed pair are proposed by all gold links. Report spans and pairs per notice, by type and distance where useful. Show coverage with annotated endpoints and with predicted endpoints. |
| Spans | Match `(doc_id, start, end, label)` exactly. Count each prediction once. Report micro precision, recall, F1, and per-type counts and scores. |
| Relations and time roles | Match an exact typed action, exact typed argument, and relation label. Report positive-link micro precision, recall, and F1 with gold endpoints and with predicted endpoints. Report argument-role and time-role Macro-F1 and confusion matrices on annotated-endpoint candidates. Show `NO_RELATION` separately so frequent negatives cannot hide missed positive links. |
| Normalized dates | On matched TIME links, score date accuracy and inference flag agreement separately on explicit, inferred, and unresolved gold subsets. Also report correct date and role over all gold TIME links, with missed links counted as failures. For the resolved-date subset, also report precision to capture extra dates. |
| Whole events | Match exact action offsets and require equality of the full set of typed arguments, their roles, and their normalized dates. Report precision, recall, F1, and exact matches divided by all gold events. |
| Applicability on annotated events | Report three-way Macro-F1, each class's precision/recall/F1 and support, the confusion matrix, and APPLIES recall. Separately report exclusions, implicit audience, missing profile attributes, and unrepresented conditions, with denominators. Keep silver and independently judged results in separate tables. |
| Applicability on predicted events | Align an event to gold by exact ACTION offsets within `doc_id` and score the same profile with predicted evidence. Report matched-event Macro-F1 with match coverage, plus joint event/profile precision, recall and F1 over all predicted and gold items. A joint match requires the agreed event match criterion and correct applicability. Unmatched gold events produce false negatives and unmatched predictions produce false positives in the joint score. Publish the match criterion. |
| Generated evidence | Report parse failure rate and unsupported evidence fields divided by all attempted evidence fields with a defined exact-source matching rule. Count invalid or rejected predicted events when explaining low coverage. If manually auditing failures, record the sampled population and sample size. |

Record how metrics treat zero support and missing classes. Use the same scoring decisions across models. For the joint event/profile score, define an evaluation profile panel per notice before running inference and pair it with every predicted and target event in scope. Use an exhaustive panel on the selected independent test notices if reporting a full joint score there. For a relation error audit, assign the first failing stage, such as absent span candidate, span boundary or type, missing pair, wrong link, wrong role, or unresolved date. Review a redacted sample of errors and include the number reviewed.

For applicability, fit a positive scalar temperature on validation logits by minimizing multiclass negative log likelihood, then apply `softmax(logits / T)`. On validation, choose a max-probability threshold using a recorded precision or coverage objective. In the application, a prediction below the threshold requests confirmation and may display `UNCLEAR`. Retain the raw predicted class and the abstention flag separately for metrics. Report Brier score or negative log likelihood, coverage, and error among accepted predictions alongside pre-abstention metrics. [Guo et al., ICML 2017](https://proceedings.mlr.press/v70/guo17a.html).

The dated split run records `gold_ready=false`. Check for a subsequent reviewed release and for group acceptance before opening test labels. If independent evaluation is pending, report development measurements with the recorded label origin and keep final ordinary and web gold-test rows pending. Follow the [gold preparation procedure](data-splitting.md#complete-gold-annotation-and-evaluation).

## Implement and hand off

Use `src/modeling/` for new reusable dataset, candidate, extractor, applicability, and metrics logic. Register it under the existing `smartnotice` package mapping in [`pyproject.toml`](../pyproject.toml). Put experiment entry points in `tools/`, using the package for shared behavior. Keep prediction and checkpoint format changes documented alongside their consumers. Use an ignored path such as `reports/generated/bamibert/<run_id>/` for generated artifacts and keep actual notice text and synthetic profile rows private.

| Order | Work | Acceptance check |
|---|---|---|
| 1 | Load and validate the frozen split. Build span tensors, relation candidate audit, and silver pairs. | One annotated document round-trips from tokenizer indices to exact text. All derived data inherits its document group. |
| 2 | Overfit a small synthetic batch and train the span warm start. | Loss decreases and predicted typed offsets match the fixture. Save validation candidate recall and exact span F1 from the real development run. |
| 3 | Add joint relation training and date decoding. | The fixture covers two actions with different deadlines, shared evidence, multiple windows, and an unresolved date. Produce gold-endpoint and predicted-endpoint validation scores. |
| 4 | Train applicability and connect inference. | The fixture demonstrates a matching profile, a mismatch, and a missing attribute. Run validation with annotated and predicted event context. |
| 5 | Package the run and evaluate the selected variants. | Reload both models, tokenizer, label maps, decision thresholds, and calibration from disk. Recreate a saved prediction from prepared text and a profile. Record pending comparisons and gold results explicitly. |

For Tuesday, 24 November, prioritize one full-fine-tuned development run and the complete notice-to-applicability demo. Make the rule candidate and Logistic Regression extraction baseline the first comparison if the complete pipeline is working. Treat grouped repeats, additional course comparisons, and LoRA as separate jobs with recorded status. Run the repository checks appropriate to the implementation, including the offline demo and relevant tests. Use a synthetic notice for the demo unless its real source has been cleared for that use.

Save the run configuration, input and split hashes, commit and lock hash, label origins and supports, model revision, seeds, candidate settings, threshold/calibration values, predictions linked by IDs, metrics and denominators, hardware, train time, peak training GPU memory, inference latency protocol, and trainable parameter counts. Keep the checkpoint and predictions tied to the run record so another contributor can reproduce the evaluation.
