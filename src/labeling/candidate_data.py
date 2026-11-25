"""Load hash-bound reviewed spans using frozen document assignments."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from smartnotice.io import read_jsonl
from smartnotice.labeling.candidates import build_candidate_targets, project_annotation_spans
from smartnotice.labeling.llm import text_sha256
from smartnotice.schemas import Notice, Span, SpanReview

DEVELOPMENT = ("train", "validation")
HOLDOUTS = ("test", "domain_test")


def _index(path):
    rows = read_jsonl(path)
    if any(
        not isinstance(row, dict) or not isinstance(row.get("doc_id"), str) or not row["doc_id"]
        for row in rows
    ):
        raise ValueError(f"Expected document IDs in {path.name}")
    indexed = {row["doc_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate document IDs in {path.name}")
    return indexed


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of the exact input file bytes."""
    return sha256(path.read_bytes()).hexdigest()


def read_candidate_notices(path: Path) -> dict[str, Notice]:
    """Read unique prepared notices and avoid including their text in validation errors."""
    result = {}
    for doc_id, row in _index(path).items():
        try:
            result[doc_id] = Notice.model_validate(row)
        except ValueError:
            raise ValueError(f"Invalid prepared notice: {doc_id}") from None
    return result


@dataclass
class ReviewedNotice:
    """Bind a prepared notice and annotation to a review and frozen group."""

    notice: Notice
    annotation: dict
    spans: list[Span]
    review: SpanReview
    group_id: str


class CandidateCorpus:
    """Load review ledgers and validate the frozen assignment before reading split text."""

    def __init__(self, snapshot: Path, reviews: Path, *, synthetic: bool):
        self.snapshot = snapshot
        self.synthetic = synthetic
        self.assignment_path = snapshot / "assignments.jsonl"
        self.assignments = _index(self.assignment_path)
        self.review_rows = _index(reviews)
        self.hashes = {
            "assignments": file_sha256(self.assignment_path),
            "span_reviews": file_sha256(reviews),
        }
        if not self.review_rows.keys() <= self.assignments.keys():
            raise ValueError("Span review ledger includes documents outside the frozen assignments")
        groups = defaultdict(set)
        for row in self.assignments.values():
            if row["split"] not in (*DEVELOPMENT, *HOLDOUTS, "excluded") or not row["group_id"]:
                raise ValueError("Invalid split or group in frozen assignments")
            groups[row["group_id"]].add(row["split"])
        if any(
            len(splits) > 1 and splits != {"domain_test", "excluded"} for splits in groups.values()
        ):
            raise ValueError("Evaluation group crosses frozen splits")
        self.source_groups = {}
        self.summary = {}

    def load(self, split: str) -> list[ReviewedNotice]:
        """Return reviewed documents for one split and record counts and input hashes.

        Held-out labels must be independent or adjudicated. Documents outside
        the review ledger are counted but do not contribute to metrics or training.
        """
        expected = {doc_id for doc_id, row in self.assignments.items() if row["split"] == split}
        review_ids = expected & self.review_rows.keys()
        if not review_ids:
            raise ValueError(f"No completed SpanReview records for {split}")
        folder = self.snapshot / split
        notice_path = folder / "notices.jsonl"
        annotation_path = folder / "annotations.jsonl"
        notices = read_candidate_notices(notice_path)
        annotations = _index(annotation_path)
        if notices.keys() != expected or not annotations.keys() <= expected:
            raise ValueError(f"Input IDs do not match frozen assignments for {split}")
        results = []
        for doc_id, notice in notices.items():
            assignment = self.assignments[doc_id]
            if text_sha256(notice) != assignment.get("text_sha256"):
                raise ValueError(f"Prepared text hash differs from frozen assignment: {doc_id}")
            if notice.synthetic != self.synthetic:
                raise ValueError(f"Synthetic flag differs from run mode: {doc_id}")
            if (split == "domain_test" and notice.source_type != "web") or (
                notice.domain_holdout and split != "domain_test"
            ):
                raise ValueError(f"Invalid domain assignment: {doc_id}")
            previous = self.source_groups.setdefault(notice.group_id, split)
            if previous != split:
                raise ValueError("Prepared notices from one source group cross evaluated splits")
            if doc_id not in review_ids:
                continue
            try:
                review = SpanReview.model_validate(self.review_rows[doc_id])
            except ValueError:
                raise ValueError(f"Invalid span review: {doc_id}") from None
            if split in HOLDOUTS and review.annotation_origin == "machine_assisted":
                raise ValueError(
                    f"Held-out evaluation requires independent or adjudicated spans: {doc_id}"
                )
            annotation = annotations.get(doc_id)
            build_candidate_targets(notice, [], annotation, review)
            results.append(
                ReviewedNotice(
                    notice,
                    annotation,
                    project_annotation_spans(notice, annotation),
                    review,
                    assignment["group_id"],
                )
            )

        self.hashes[f"{split}_notices"] = file_sha256(notice_path)
        self.hashes[f"{split}_annotations"] = file_sha256(annotation_path)
        self.summary[split] = {
            "assigned": len(expected),
            "reviewed": len(results),
            "sources": dict(Counter(item.notice.source_type for item in results)),
            "origins": dict(Counter(item.review.annotation_origin for item in results)),
            "groups": len({item.group_id for item in results}),
        }
        return results
