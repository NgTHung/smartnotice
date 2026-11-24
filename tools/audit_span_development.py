"""Summarize candidate research inputs without exporting notice text."""

import argparse
import hashlib
import json
import platform
from collections import Counter, defaultdict
from pathlib import Path

from smartnotice.io import read_jsonl
from smartnotice.labeling.candidates import build_candidate_targets, project_annotation_spans
from smartnotice.labeling.llm import text_sha256
from smartnotice.schemas import Notice, SpanReview


def _index(rows, kind):
    indexed = {row["doc_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate document in {kind}")
    return indexed


def main() -> None:
    """Print aggregate split and span evidence as JSON for a frozen split directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--span-reviews", type=Path)
    args = parser.parse_args()
    snapshot = args.snapshot
    paths = {"assignments": snapshot / "assignments.jsonl"}
    assignments = _index(read_jsonl(paths["assignments"]), "assignments")
    review_rows = {}
    if args.span_reviews is not None:
        paths["span_reviews"] = args.span_reviews
        review_rows = _index(read_jsonl(args.span_reviews), "span reviews")
    groups = defaultdict(set)
    for row in assignments.values():
        groups[row["group_id"]].add(row["split"])
    if any(len(splits) > 1 and splits != {"domain_test", "excluded"} for splits in groups.values()):
        raise ValueError("Evaluation group crosses splits")

    development = {}
    used_reviews = set()
    for split in ("train", "validation"):
        paths[f"{split}_notices"] = snapshot / split / "notices.jsonl"
        paths[f"{split}_annotations"] = snapshot / split / "annotations.jsonl"
        notices = _index(read_jsonl(paths[f"{split}_notices"]), f"{split} notices")
        annotations = _index(read_jsonl(paths[f"{split}_annotations"]), f"{split} annotations")
        expected = {doc_id for doc_id, row in assignments.items() if row["split"] == split}
        if notices.keys() != expected or not annotations.keys() <= expected:
            raise ValueError(f"{split} document IDs do not match assignments")
        span_counts = Counter()
        counts = Counter()
        verified = Counter()
        sources = Counter()
        for doc_id, row in notices.items():
            try:
                notice = Notice.model_validate(row)
                review = (
                    SpanReview.model_validate(review_rows[doc_id])
                    if doc_id in review_rows
                    else None
                )
            except ValueError:
                raise ValueError(f"Invalid notice or span review: {doc_id}") from None
            assignment_hash = assignments[doc_id].get("text_sha256")
            if assignment_hash is not None and assignment_hash != text_sha256(notice):
                raise ValueError(f"Prepared text differs from split assignment: {doc_id}")
            sources[notice.source_type] += 1
            annotation = annotations.get(doc_id)
            if review is not None:
                build_candidate_targets(notice, [], annotation, review)
                used_reviews.add(doc_id)
                verified[review.annotation_origin] += 1
            if annotation is not None:
                spans = project_annotation_spans(notice, annotation)
                span_counts.update(
                    label for label, _, _ in {(s.label, s.start, s.end) for s in spans}
                )
                counts["span_rows"] += len(spans)
        development[split] = {
            "documents": len(notices),
            "sources": dict(sources),
            "annotated_documents_with_valid_spans": len(annotations),
            "span_rows": counts["span_rows"],
            "distinct_typed_spans": dict(span_counts),
            "complete_span_reviews_by_origin": dict(verified),
        }
    if review_rows.keys() != used_reviews:
        raise ValueError("Span review input contains documents outside the development splits")

    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "sha256": {
                    name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for name, path in paths.items()
                },
                "uv_lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
                "assignment_counts": dict(Counter(row["split"] for row in assignments.values())),
                "assignment_seeds": sorted({row["seed"] for row in assignments.values()}),
                "assignment_similarities": sorted(
                    {row["similarity"] for row in assignments.values()}
                ),
                "group_count": len(groups),
                "development": development,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
