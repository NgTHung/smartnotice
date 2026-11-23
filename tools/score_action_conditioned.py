"""Validate Kaggle predictions against prepared text and score the frozen extraction run."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from compare_notice_pipelines import _metrics, _test_docs
from smartnotice.modeling.data import labeled_links, load_development, sha256, span_key
from smartnotice.modeling.experiment import write_summary
from smartnotice.modeling.extraction import decode_notice
from smartnotice.modeling.metrics import prf, span_scores


def _score(docs, raw):
    rows = {r["doc_id"]: r for r in raw}
    if len(rows) != len(raw) or rows.keys() != {d.notice.doc_id for d in docs}:
        raise ValueError("Prediction IDs differ from frozen split")
    outputs, original_spans, gold = {}, set(), set()
    ambiguous = 0
    with_action = 0
    with_both = 0
    recovered = 0
    cross_sentence = [0, 0]
    for doc in docs:
        notice = doc.notice
        row = rows[notice.doc_id]
        spans = {tuple(s) for s in row["spans"]}
        for start, end, _ in spans:
            if not any(s.start <= start < end <= s.end for s in notice.sentences):
                raise ValueError("A predicted span falls outside its source sentence")
        first_stage = {tuple(s) for s in row["stage_one_spans"]}
        original_spans.update((notice.doc_id, *s) for s in first_stage)
        gold.update((notice.doc_id, *span_key(s)) for s in doc.annotation.spans)
        pairs = defaultdict(set)
        for action, argument, role in row["links"]:
            a, b = tuple(action), tuple(argument)
            if a not in spans or b not in spans or a[2] != "ACTION":
                raise ValueError("Predicted link lacks a typed endpoint")
            pairs[a, b].add(role)
        # The contract permits one role for each argument of a particular action.
        ambiguous += sum(len(roles) > 1 for roles in pairs.values())
        links = {(a, b, next(iter(roles))) for (a, b), roles in pairs.items() if len(roles) == 1}
        targets = labeled_links(doc.annotation)
        with_action += sum(a in first_stage for a, b, role in targets)
        with_both += sum(a in first_stage and b in first_stage for a, b, role in targets)
        recovered += sum(b not in first_stage for a, b, role in targets & links)
        for a, b, role in targets:
            if not any(
                s.start <= min(a[0], b[0]) and max(a[1], b[1]) <= s.end for s in notice.sentences
            ):
                cross_sentence[0] += (a, b, role) in links
                cross_sentence[1] += 1
        outputs[notice.doc_id] = spans, decode_notice(notice, spans, links, "action-conditioned")
    predicted_types, expected_types = defaultdict(set), defaultdict(set)
    for ident, (spans, _) in outputs.items():
        for a, b, label in spans:
            predicted_types[ident, a, b].add(label)
    for ident, a, b, label in gold:
        expected_types[ident, a, b].add(label)
    aligned = expected_types.keys() & predicted_types.keys()
    return {
        **_metrics(docs, outputs),
        "stage_one_spans": span_scores(gold, original_spans),
        "untyped_boundary": prf(set(expected_types), set(predicted_types)),
        "correct_label_sets_on_matching_boundaries": sum(
            expected_types[k] == predicted_types[k] for k in aligned
        ),
        "ambiguous_pairs_omitted": ambiguous,
        "reference_links_with_predicted_action": with_action,
        "reference_links_with_both_stage_one_spans": with_both,
        "correct_links_to_arguments_missed_by_stage_one": recovered,
        "cross_sentence_links_matched_expected": cross_sentence,
        "documents": len(docs),
        "groups": len({d.group_id for d in docs}),
    }


def main() -> None:
    """Score downloaded offsets without sending test reference labels to the training host."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads((args.run / "run.json").read_text(encoding="utf8"))
    development, provenance = load_development(args.split)
    if metadata["provenance"]["hashes"] != provenance["hashes"]:
        raise ValueError("Kaggle training or validation input differs from the release")
    report = {"kaggle_run_sha256": sha256(args.run / "run.json")}
    for part, docs in (("validation", development["validation"]), ("test", _test_docs(args.split))):
        path = args.run / f"{part}-predictions.json"
        report[part] = _score(docs, json.loads(path.read_text(encoding="utf8")))
        report[part]["predictions_sha256"] = sha256(path)
    write_summary(args.run / "local_scores.json", report)
    for part in ("validation", "test"):
        print(part, report[part]["link"]["micro"], report[part]["event"])


if __name__ == "__main__":
    main()
