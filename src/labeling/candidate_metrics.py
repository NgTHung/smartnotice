"""Measure generator coverage and exact typed-span filtering separately."""

from collections import Counter
from math import ceil
from statistics import mean, median

from smartnotice.labeling.candidate_generation import LABELS
from smartnotice.schemas import CandidateTarget


def _ratio(num, den):
    return num / den if den else None


def _prf(tp, fp, fn):
    return {
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "f1": _ratio(2 * tp, 2 * tp + fp + fn),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def _aggregate(documents, label=None):
    total = Counter()
    per_document = []
    for doc in documents:
        gold = {key for key in doc["gold"] if label is None or key[2] == label}
        emitted = {key for key in doc["emitted"] if label is None or key[2] == label}
        kept = emitted & doc["kept"]
        covered = gold & emitted
        per_document.append(len(emitted))
        total.update(
            {
                "gold": len(gold),
                "generated_gold": len(covered),
                "overlap_gold": sum(
                    any(
                        start < other_end and other_start < end and kind == other_kind
                        for other_start, other_end, other_kind in emitted
                    )
                    for start, end, kind in gold
                ),
                "candidates": len(emitted),
                "kept": len(kept),
                "tp": len(kept & gold),
            }
        )
    gold, generated = total["gold"], total["generated_gold"]
    candidates, kept, tp = total["candidates"], total["kept"], total["tp"]
    fp = kept - tp
    return {
        "documents": len(documents),
        "gold": gold,
        "exact_generated_gold": generated,
        "overlap_generated_gold": total["overlap_gold"],
        "candidate_recall": _ratio(generated, gold),
        "overlap_coverage": _ratio(total["overlap_gold"], gold),
        "candidates": candidates,
        "candidates_per_document": {
            "mean": mean(per_document) if per_document else None,
            "median": median(per_document) if per_document else None,
            "p95": sorted(per_document)[ceil(len(per_document) * 0.95) - 1]
            if per_document
            else None,
        },
        "binary_positive": _prf(tp, fp, generated - tp),
        "binary_negative": _prf(candidates - generated - fp, generated - tp, fp),
        "binary_confusion": {
            "tp": tp,
            "fp": fp,
            "fn": generated - tp,
            "tn": candidates - generated - fp,
        },
        "exact_typed_span": _prf(tp, fp, gold - tp),
        "gold_missed_by_generator": gold - generated,
        "generated_gold_rejected": generated - tp,
        "generated_gold_rejection_rate": _ratio(generated - tp, generated),
    }


def evaluate_candidates(documents: list[dict]) -> dict:
    """Report metrics for reviewed documents, including those with no candidates.

    Each document contributes gold, emitted and kept sets of (start, end, label)
    keys. Undefined ratios are returned as None. No pooling crosses documents.
    """
    return {
        "overall": _aggregate(documents),
        "by_label": {label: _aggregate(documents, label) for label in LABELS},
        "by_source": {
            source: _aggregate([doc for doc in documents if doc["source"] == source])
            for source in sorted({doc["source"] for doc in documents})
        },
    }


def select_threshold(scores, targets: list[CandidateTarget], gold_count: int) -> float:
    """Maximize exact typed-span F1 on validation, preferring higher recall on ties."""
    hits = kept = 0
    best = (0.0, 0, 2.0)
    in_order = sorted(zip(scores, targets, strict=True), key=lambda pair: pair[0], reverse=True)
    for index, (score, target) in enumerate(in_order):
        hits += target.target == 1
        kept += 1
        if index + 1 == len(in_order) or in_order[index + 1][0] != score:
            best = max(best, (2 * hits / (gold_count + kept), hits, -float(score)))
    # The no-prediction operating point uses a finite threshold above 1.
    return -best[2] if best[2] != 2.0 else 1.01
