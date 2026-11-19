"""Fit a local follow-up item scorer from source-validated train packets."""

import argparse
import hashlib
import json
import platform
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from smartnotice.io import read_jsonl
from smartnotice.labeling.event_groups import build_event_groups
from smartnotice.labeling.grouping_alignment import build_followup_profiles
from smartnotice.labeling.grouping_followup import (
    RoutingComparison,
    compare_routing,
    load_email_routing,
)
from smartnotice.labeling.grouping_rerank import fit_followup_reranker, followup_rerank_features
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import Annotation, GroupingModelMention, Notice


class TrainPair(BaseModel):
    """Read the fitting fields from an attributed item review row."""

    review_id: str
    left: str
    right: str
    target_decision: Literal["MATCH", "OTHER", "UNCLEAR"]
    split: Literal["train"]
    reply_side: Literal[0, 1] | None = None


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _examples(
    directory: Path, raw_email_dir: Path, synthetic_raw_email_dir: Path | None = None
) -> tuple[dict[frozenset[str], tuple[tuple[float, ...], bool]], dict]:
    files = [directory / name for name in ("notices.jsonl", "annotations.jsonl", "pairs.jsonl")]
    parsed_notices = [Notice.model_validate(row) for row in read_jsonl(files[0])]
    notices = {notice.doc_id: notice for notice in parsed_notices}
    if len(notices) != len(parsed_notices):
        raise ValueError("Duplicate document in follow-up training packet")
    annotations = [Annotation.model_validate(row) for row in read_jsonl(files[1])]
    assembly = build_event_groups(parsed_notices, annotations, [])
    mentions_by_doc = defaultdict(list)
    for item in assembly.mentions:
        ref = item.version.event_ref
        doc_id = ref.partition(":")[0]
        mention = GroupingModelMention(
            mention_id=ref,
            doc_id=doc_id,
            version=item.version,
            event=item.event,
            spans=item.spans,
            sentences=item.sentences,
        )
        mentions_by_doc[doc_id].append(mention)
    headers = {
        doc_id: load_email_routing(
            notices[doc_id],
            (synthetic_raw_email_dir or raw_email_dir)
            if notices[doc_id].synthetic
            else raw_email_dir,
        )
        for doc_id in mentions_by_doc
    }
    profiles = {
        p.mention_id: p
        for doc_id, mentions in mentions_by_doc.items()
        for p in build_followup_profiles(notices[doc_id], mentions, headers[doc_id])
    }
    pairs = [TrainPair.model_validate(row) for row in read_jsonl(files[2])]
    output = {}
    seen = set()
    unscored = Counter()
    for row in pairs:
        key = frozenset((row.left, row.right))
        left, right = profiles.get(row.left), profiles.get(row.right)
        if (
            len(key) != 2
            or key in seen
            or left is None
            or right is None
            or left.doc_id == right.doc_id
        ):
            raise ValueError(f"Invalid or duplicate follow-up review {row.review_id}")
        seen.add(key)
        if row.target_decision == "UNCLEAR":
            unscored["unresolved_review"] += 1
            continue
        if row.reply_side is None:
            unscored["outside_direct_reply_task"] += 1
            continue
        routing = compare_routing(headers[left.doc_id], headers[right.doc_id])
        if (
            notices[left.doc_id].synthetic
            and notices[right.doc_id].synthetic
            and (headers[left.doc_id] is None and headers[right.doc_id] is None)
        ):
            routing = RoutingComparison(row.reply_side, None, False, True)
        if not routing.direct_parent or routing.later != row.reply_side:
            raise ValueError(f"Reply direction disagrees with verified sources for {row.review_id}")
        parent, reply = (left, right) if row.reply_side == 1 else (right, left)
        output[key] = followup_rerank_features(parent, reply), row.target_decision == "MATCH"
    return output, {
        "directory": directory.as_posix(),
        "source_sha256": {path.name: _digest(path) for path in files},
        "reviewed": len(pairs),
        "fitted": len(output),
        "positive": sum(label for _, label in output.values()),
        "excluded": dict(unscored),
        "synthetic": all(notice.synthetic for notice in notices.values()),
    }


def main() -> None:
    """Fit a checkpoint after validating source items and train-only review rows."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, action="append", required=True)
    parser.add_argument("--raw-email-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--synthetic-raw-email-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    root = Path("reports/generated").resolve()
    if destination == root or not destination.is_relative_to(root) or destination.exists():
        parser.error("Choose a new output directory under reports/generated")
    if not args.raw_email_dir.is_dir() or (
        args.synthetic_raw_email_dir is not None and not args.synthetic_raw_email_dir.is_dir()
    ):
        parser.error("Choose existing local email directories")

    all_rows = {}
    packets = []
    for directory in args.data_dir:
        data, provenance = _examples(directory, args.raw_email_dir, args.synthetic_raw_email_dir)
        if all_rows.keys() & data.keys():
            raise ValueError("Training packets overlap in reviewed mention pairs")
        all_rows.update(data)
        packets.append(provenance)
    features, labels = zip(*all_rows.values(), strict=True) if all_rows else ((), ())
    model = fit_followup_reranker(features, labels, seed=args.seed)

    import sklearn

    destination.mkdir(parents=True)
    checkpoint = destination / "model.json"
    checkpoint.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    code = [
        Path(__file__),
        Path("src/labeling/grouping_alignment.py"),
        Path("src/labeling/grouping_rerank.py"),
        Path("src/labeling/grouping_followup.py"),
        Path("uv.lock"),
    ]
    record = {
        "kind": model.kind,
        "seed": args.seed,
        "threshold": model.threshold,
        "margin": model.margin,
        "fitted": len(labels),
        "positive": sum(labels),
        "negative": len(labels) - sum(labels),
        "packets": packets,
        "model_sha256": _digest(checkpoint),
        "code_sha256": {path.as_posix(): _digest(path) for path in code},
        "environment": {"python": platform.python_version(), "scikit_learn": sklearn.__version__},
    }
    (destination / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: record[key] for key in ("kind", "fitted", "positive", "negative")}))


if __name__ == "__main__":
    main()
