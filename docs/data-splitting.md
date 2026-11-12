# Freeze grouped dataset splits

Use a frozen document assignment to keep related notices out of different evaluation sets. This procedure prepares a reviewed curated snapshot for training and independent test annotation, then preserves existing assignments when the corpus grows. The [data contract](interface.md#separate-evaluation-groups) owns the output fields and validation rules.

## Choose the split workflow

`uv run smartnotice split` allocates whole groups near 65/15/20 by document count, with a default similarity threshold of 0.9. It does not stratify annotations or preserve earlier assignments. Use it for an initial size-only split or the synthetic demo.

For a curated research corpus, use `tools/freeze_curated_split.py`. It defaults to similarity 0.8, reserves a separate web holdout, balances annotation features and preserves assignments supplied through `--previous`. The [12 November 2026 split record](../reports/split-2026-11-12.md) identifies the published v3.1 allocation and its limitations.

## Prepare reviewed input

Place these files in a private input directory:

| File | Required content |
|---|---|
| `notices.jsonl` | Prepared notices with stable document IDs, text, offsets, source groups and source references |
| `annotations.jsonl` | Exactly one canonical annotation for every notice |
| `human_review.json` | Recorded privacy and annotation review, with `privacy_review_completed=true`, `human_review_completed=true`, `snapshot.files_sha256`, `annotation_origin` and `privacy_review_basis` |
| `checksums.json` | The original snapshot's file-hash manifest, retained with the release |

The utility compares the notice and annotation file hashes with `human_review.json` and validates annotation spans and event links. Do not set review fields to bypass missing human review. Preserve machine-assisted annotation origin; review of a suggestion is different from independent double annotation or adjudication. Follow the [annotation procedure](annotation.md) for those activities.

The initial holdout procedure requires at least 50 web notices and enough web-only groups to reserve 40–50 notices covering every source site. Verify publication metadata and source grouping before running it. The utility records manual group review as incomplete; software grouping does not establish human acceptance of the groups.

## Create the first release

Run from the repository root using the environment in the [README](../README.md):

```powershell
uv run python tools/freeze_curated_split.py --input path/to/reviewed-snapshot --output data/processed/frozen-v1 --similarity 0.8 --seed 42 --seed-count 100
```

The output directory must not exist. The run performs these allocation steps:

1. Sort documents by `doc_id`, merge source thread/template groups and near duplicates transitively, and keep every group intact.
2. Sample web-only groups toward a 45-notice holdout, balancing site counts relative to each site's share of the web corpus. The holdout sampling uses `--seed`. Groups already marked `domain_holdout` are also reserved; they can increase the total beyond the sampling target. Related email in a reserved group receives `excluded`.
3. Apply 65/15/20 to the remaining ordinary pool. Balance document count, email/web source, the six span-label counts, CONDITION presence, representable `listed` audiences and `outside_population` presence. The representable category means `scope=listed` and `unrepresented=false`.
4. Minimize normalized squared deviations from each target share, giving each feature equal weight after normalization by its corpus total. Allocate whole groups greedily, then make up to 20 passes of improving whole-group moves. Exact proportions are not guaranteed.
5. Try the requested consecutive seed range. Select the lowest count-balance score, breaking equal scores by the smaller seed. Never use model predictions, errors or evaluation scores to choose the seed.

By default the candidate seeds are 42–141. The seed influences tie ordering; different seeds can yield the same allocation. Record the complete search rather than interpreting seed selection as evidence of model quality.

## Inspect and accept the release

Review `group_review.jsonl` against the prepared source text, especially broad threads, repeated boilerplate and transitive merges. Short replies and corrections can legitimately share a group with a longer notice. Record actual human group acceptance separately; do not change the utility's review flags without that review.

Use the output files according to their role:

| Output | Use |
|---|---|
| `assignments.jsonl` | Join `doc_id` to split/group and check text, input-file hash, seed and threshold |
| `record.json` | Inspect source/code/lock hashes, Python version, split counts, feature counts and review limitations |
| `seed_search.json` | Audit the count-balance score of every candidate seed |
| `train/`, `validation/` | Consume prepared notices and their existing annotations |
| `test/`, `domain_test/` | Import unlabeled tasks and track independent annotation and adjudication |
| `excluded/` | Retain notices excluded because their reserved group must remain outside the ordinary pool |
| `reference_only_do_not_train_on_test/` | Preserve historical annotations and the source review record locally; keep this directory away from independent annotators and model inputs |

Notice rows preserve their source snapshot, including earlier privacy and holdout flags. Use `assignments.jsonl` as the allocation authority; the task export records the matching subsequent privacy-review basis. Every event/profile pair must inherit its document's assignment. Do not split derived pairs independently.

The utility does not build a delivery ZIP. A delivery for independent annotators must omit historical held-out annotations, include the matching privacy-review record and group assignments, and keep a checksum manifest for its actual files. The v3.1 delivery layout is recorded in the [dated run report](../reports/split-2026-11-12.md).

## Complete gold annotation and evaluation

Import the same `independent_annotation_tasks.json` into two separate Label Studio projects using the labeling configuration in `data/annotations/label_studio.xml`. Each annotator works without predictions, historical labels or the other's export. Preserve both exports before adjudication. Validate the adjudicated canonical annotation against the frozen text and record the real reviewers and decisions before marking a held-out document `gold_ready`.

Until those steps are complete, treat test and domain-test as reserved documents awaiting gold labels. They are not completed gold evaluation sets. The [evaluation protocol](evaluation.md) owns fitting, grouped cross-validation, calibration and final test use.

## Extend a frozen release

Prepare a newly reviewed cumulative snapshot containing every old document plus the additions. Keep the old release unchanged and run:

```powershell
uv run python tools/freeze_curated_split.py --input path/to/cumulative-reviewed-snapshot --output data/processed/frozen-v2 --previous data/processed/frozen-v1 --similarity 0.8 --seed 42 --seed-count 100
```

The utility requires the same similarity threshold. Old documents keep their splits; new documents joining a frozen group inherit its split. A new near duplicate of a test document therefore joins test. Existing web holdout membership stays reserved; related email is excluded. Only new unpinned groups participate in allocation and refinement, so proportions can drift as the corpus grows.

The run rejects missing old documents, changed bound text, incompatible reserved memberships and a new merge connecting previously distinct splits. Resolve such conflicts explicitly in a versioned re-freeze or revise the cumulative input under a documented exclusion policy. Do not run the ordinary `split` command over the corpus to overwrite frozen assignments.

An optional `--group-map path/to/groups.json` reuses an earlier grouping computation. Its companion `groups.record.json` must contain `data_sha256`, `similarity` and `groups_sha256` matching the current input and mapping. This verifies the cache binding; inspect its computation provenance before trusting it. A cache from an earlier corpus cannot be reused for a larger corpus.
