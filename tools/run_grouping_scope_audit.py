"""Score a saved email candidate batch with and without academic scope."""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.grouping_academic import academic_scope, apply_academic_scope
from smartnotice.labeling.grouping_evidence import compare_pair_evidence, evidence_decision
from smartnotice.labeling.grouping_followup import followup_evidence, load_email_routing
from smartnotice.labeling.grouping_model import (
    grouping_probability,
    pair_features,
    validate_grouping_mention,
)
from smartnotice.schemas import (
    EventGroupAssembly,
    GroupingLinearModel,
    GroupingModelMention,
    Notice,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """Write private predictions and counts for all candidates in a saved assembly."""
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("notices", "assembly", "checkpoint", "output-dir", "raw-email-dir"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    root = Path("reports/generated").resolve()
    output = args.output_dir.resolve()
    if not output.is_relative_to(root) or output == root or output.exists():
        parser.error("Choose a new directory under reports/generated")
    if not args.raw_email_dir.is_dir():
        parser.error("The raw email directory does not exist")
    checkpoint = GroupingLinearModel.model_validate_json(args.checkpoint.read_bytes())
    if checkpoint.kind != "grouping-logistic-v2":
        parser.error("Expected the evidence checkpoint")
    inputs = [
        args.notices,
        args.assembly,
        args.checkpoint,
        Path(__file__),
        Path("src/labeling/grouping_academic.py"),
        Path("src/labeling/grouping_evidence.py"),
        Path("src/labeling/grouping_followup.py"),
        Path("src/labeling/grouping_model.py"),
        Path("src/parsers/email.py"),
        Path("uv.lock"),
    ]
    hashes = {p.as_posix(): _sha(p) for p in inputs}
    source = [Notice.model_validate(row) for row in read_jsonl(args.notices)]
    notices = {notice.doc_id: notice for notice in source}
    if len(notices) != len(source):
        raise ValueError("Duplicate source document ID")
    assembly = EventGroupAssembly.model_validate_json(args.assembly.read_bytes())
    mentions, scopes, headers = {}, {}, {}
    for item in assembly.mentions:
        ref = item.version.event_ref
        did = ref.partition(":")[0]
        m = GroupingModelMention(
            mention_id=ref, doc_id=did, **item.model_dump(exclude={"annotation_origin"})
        )
        if ref in mentions:
            raise ValueError("Duplicate event reference in saved assembly")
        validate_grouping_mention(m, notices[did])
        if did not in headers:
            headers[did] = load_email_routing(notices[did], args.raw_email_dir)
        mentions[ref] = m
        scopes[ref] = academic_scope(m, notices[did], headers[did])
    predictions = []
    seen = set()
    for pair in assembly.reviews:
        left, right = pair.left.event_ref, pair.right.event_ref
        key = frozenset((left, right))
        if key in seen or len(key) != 2:
            raise ValueError("Duplicate pair in saved assembly")
        seen.add(key)
        a, b = mentions[left], mentions[right]
        docs = (notices[a.doc_id], notices[b.doc_id])
        evidence = compare_pair_evidence(a, b, *docs)
        follow = followup_evidence(a, b, docs, (headers[a.doc_id], headers[b.doc_id]), evidence)
        score = grouping_probability(checkpoint, pair_features(a, b) + evidence.features)
        base = evidence_decision(score, checkpoint.threshold, evidence)
        if follow.joint:
            base = "SAME_EVENT"
        decision = apply_academic_scope(scopes[left], scopes[right], follow.routing, base)
        predictions.append(
            {
                "pair_id": pair.review_id,
                "left": left,
                "right": right,
                "base_decision": base,
                **asdict(decision),
            }
        )
    result = {
        "kind": "unlabeled_cached_candidate_audit",
        "documents": len(notices),
        "documents_with_mentions": len(headers),
        "verified_raw_documents": sum(h is not None for h in headers.values()),
        "mentions": len(mentions),
        "candidate_pairs": len(predictions),
        "before": dict(sorted(Counter(row["base_decision"] for row in predictions).items())),
        "after": dict(sorted(Counter(row["decision"] for row in predictions).items())),
        "changes": dict(
            sorted(
                Counter(
                    f"{row['base_decision']}->{row['decision']}"
                    for row in predictions
                    if row["base_decision"] != row["decision"]
                ).items()
            )
        ),
        "academic_reasons": dict(sorted(Counter(row["reason"] for row in predictions).items())),
        "inputs_sha256": hashes,
    }
    if any(_sha(p) != hashes[p.as_posix()] for p in inputs):
        raise ValueError("An input changed during scoring")
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / "predictions.jsonl", predictions)
    (output / "run.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "inputs_sha256"}, indent=2))


if __name__ == "__main__":
    main()
