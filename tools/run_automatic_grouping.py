"""Propose pairs, assemble groups and export an offline review page in one run."""

import argparse
import hashlib
import json
import platform
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.automatic_grouping import (
    compare_grouping_reference,
    propose_event_groups,
)
from smartnotice.labeling.group_viewer import render_group_review
from smartnotice.labeling.studio import import_prediction_tasks
from smartnotice.schemas import (
    Annotation,
    AutomaticGroupingConfig,
    EventGroupAssembly,
    GroupingLinearModel,
    Notice,
    TimeBoundaryReview,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path, model: type) -> list:
    records = []
    for number, row in enumerate(read_jsonl(path), 1):
        try:
            records.append(model.model_validate(row))
        except ValueError:
            raise ValueError(f"Invalid {model.__name__} on line {number}") from None
    return records


def _dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Validate all outputs before writing to a new private directory.

    Accept canonical annotations or a complete batch of saved model predictions.
    Preserve model authorship and retain empty annotations in the output snapshot.
    An evidence checkpoint can assist pair proposals using local source evidence.
    A reference assembly is read only for diagnostics after proposals are built.
    No approval is inherited by new groups, even when membership matches. Source
    text, saved reviews, previous HTML and evaluation splits remain unchanged.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notices", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--annotations", type=Path)
    source.add_argument("--predictions", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--time-boundaries", type=Path)
    parser.add_argument("--reference-assembly", type=Path)
    parser.add_argument("--checkpoint", type=Path, help="Optional grouping-logistic-v2 checkpoint")
    parser.add_argument("--raw-email-dir", type=Path, help="Local hash-named email source files")
    parser.add_argument("--generated-at", type=datetime.fromisoformat)
    parser.add_argument("--candidate-similarity", type=float, default=0.35)
    parser.add_argument("--min-shared-tokens", type=int, default=3)
    args = parser.parse_args()
    if args.raw_email_dir is not None and args.checkpoint is None:
        parser.error("--raw-email-dir requires --checkpoint")
    if args.raw_email_dir is not None and not args.raw_email_dir.is_dir():
        parser.error("--raw-email-dir must be an existing directory")
    root, output = Path.cwd().resolve(), args.output_dir.resolve()
    if not any(output.is_relative_to(root / p) for p in ["data/processed", "reports/generated"]):
        raise ValueError("Output must stay in data/processed or reports/generated")
    if output.exists():
        raise ValueError("Output already exists; choose a new directory")
    template = Path(__file__).parent / "templates/group_review.html.template"
    inputs = [args.notices, args.annotations or args.predictions]
    inputs += [p for p in [args.time_boundaries, args.reference_assembly, args.checkpoint] if p]
    code = [
        Path(__file__),
        Path("src/labeling/automatic_grouping.py"),
        Path("src/labeling/event_groups.py"),
        Path("src/labeling/group_viewer.py"),
        Path("src/labeling/studio.py"),
        Path("src/labeling/validation.py"),
        Path("src/labeling/llm.py"),
        Path("src/schemas.py"),
        Path("uv.lock"),
        template,
    ]
    if args.checkpoint is not None:
        code.extend(
            [
                Path("src/labeling/grouping_academic.py"),
                Path("src/labeling/grouping_evidence.py"),
                Path("src/labeling/grouping_followup.py"),
                Path("src/labeling/grouping_model.py"),
                Path("src/parsers/addresses.py"),
                Path("src/parsers/email.py"),
            ]
        )
    before = {p.as_posix(): _sha(p) for p in inputs + code}
    checkpoint = (
        GroupingLinearModel.model_validate_json(args.checkpoint.read_bytes())
        if args.checkpoint is not None
        else None
    )
    notices = _read(args.notices, Notice)
    if args.predictions:
        try:
            tasks = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
            annotations = import_prediction_tasks(tasks, notices)
        except (ValueError, KeyError, TypeError):
            raise ValueError(
                "Invalid saved predictions; check structure, source hashes and spans privately"
            ) from None
        if {a.doc_id for a in annotations} != {n.doc_id for n in notices}:
            raise ValueError("Saved predictions must cover exactly the supplied Notice documents")
    else:
        annotations = _read(args.annotations, Annotation)
    raw_hashes = set()
    if args.raw_email_dir is not None:
        used_docs = {label.doc_id for label in annotations if label.events}
        raw_hashes = {
            notice.raw_sha256
            for notice in notices
            if notice.doc_id in used_docs
            and notice.source_type == "email"
            and re.fullmatch(r"[a-f0-9]{64}", notice.raw_sha256)
        }
    raw_files = {digest: args.raw_email_dir / f"{digest}.eml" for digest in raw_hashes}
    raw_available = {digest for digest, path in raw_files.items() if path.is_file()}
    result = propose_event_groups(
        notices,
        annotations,
        generated_at=args.generated_at or datetime.now(UTC),
        config=AutomaticGroupingConfig(
            candidate_similarity=args.candidate_similarity, min_shared_tokens=args.min_shared_tokens
        ),
        time_boundaries=_read(args.time_boundaries, TimeBoundaryReview)
        if args.time_boundaries
        else None,
        checkpoint=checkpoint,
        raw_email_dir=args.raw_email_dir,
    )
    comparison = None
    if args.reference_assembly:
        reference = EventGroupAssembly.model_validate_json(args.reference_assembly.read_bytes())
        comparison = compare_grouping_reference(result, reference)
    html = render_group_review(result.assembly, notices, template.read_text(encoding="utf-8"))
    if any(_sha(p) != before[p.as_posix()] for p in inputs + code):
        raise ValueError("Input or implementation changed during the run")
    if raw_available != {digest for digest, path in raw_files.items() if path.is_file()} or any(
        _sha(raw_files[digest]) != digest for digest in raw_available
    ):
        raise ValueError("Local email sources changed during the run")
    counts = {
        "documents": len(notices),
        "annotation_documents": len(annotations),
        "empty_annotation_documents": sum(not a.events for a in annotations),
        "mentions": len(result.assembly.mentions),
        "compared_pairs": result.compared_pairs,
        "candidate_pairs": len(result.proposals),
        "decisions": dict(sorted(Counter(p.pair.decision for p in result.proposals).items())),
        "groups": len(result.assembly.groups),
        "multi_mention_groups": sum(len(g.members) > 1 for g in result.assembly.groups),
        "tasks": sum(len(g.tasks) for g in result.assembly.groups),
        "applied_updates": sum(u.applied for u in result.assembly.updates),
        "conflicts": len(result.assembly.conflicts),
    }
    diagnostics = None
    if comparison:
        diagnostics = {
            "explicit_reference_pairs": len(comparison.pairs),
            "candidate_pairs_found": sum(p.proposed_decision is not None for p in comparison.pairs),
            "pairs_without_reported_mismatch": sum(not p.issues for p in comparison.pairs),
            "issues": dict(sorted(Counter(i for p in comparison.pairs for i in p.issues).items())),
            "independent_evaluation": False,
        }
    run = {
        "created_at": result.generated_at.isoformat(),
        "rule_version": result.rule_version,
        "config": result.config.model_dump(),
        "source_sha256": before,
        "environment": {"python": platform.python_version(), "system": platform.system()},
        "workflow_counts": counts,
        "development_diagnostics": diagnostics,
        "label_origin": "rule_proposals_over_model_predictions"
        if args.predictions
        else "rule_proposals_over_supplied_annotations",
        "randomness": None,
        "quality_measured": False,
        "human_approval_created": False,
        "privacy_approval_created": False,
        "split_assignments_changed": False,
        "reference_used_for_prediction": False,
    }
    if checkpoint is not None:
        run["checkpoint"] = {
            "kind": checkpoint.kind,
            "threshold": checkpoint.threshold,
            "local_raw_email_requested": args.raw_email_dir is not None,
            "verified_email_source_hashes": sorted(raw_available),
        }
        run["label_origin"] = run["label_origin"].replace(
            "rule_proposals", "model_assisted_rule_proposals"
        )
    output.mkdir(parents=True)
    write_jsonl(output / "annotations.jsonl", [a.model_dump(mode="json") for a in annotations])
    _dump(output / "result.json", result.model_dump(mode="json"))
    _dump(output / "assembly.json", result.assembly.model_dump(mode="json"))
    write_jsonl(
        output / "pair_proposals.jsonl", [p.model_dump(mode="json") for p in result.proposals]
    )
    write_jsonl(
        output / "pair_decisions.jsonl", [p.pair.model_dump(mode="json") for p in result.proposals]
    )
    write_jsonl(
        output / "groups.jsonl", [g.model_dump(mode="json") for g in result.assembly.groups]
    )
    write_jsonl(
        output / "conflicts.jsonl", [c.model_dump(mode="json") for c in result.assembly.conflicts]
    )
    (output / "index.html").write_text(html, encoding="utf-8")
    if comparison:
        _dump(output / "comparison.json", comparison.model_dump(mode="json"))
        lines = [
            "# Đối chiếu trên mẫu phát triển",
            "",
            "Chỉ đối chiếu các cặp đã có; không suy nhãn từ nhóm đơn. "
            "Đây không phải đánh giá độc lập hoặc số đo chất lượng.",
            "",
            "| Cặp tham chiếu | Nhãn tham chiếu | Nhãn đề xuất | "
            "Quan hệ việc tham chiếu | Quan hệ việc đề xuất | Vấn đề | Xem nguồn |",
            "|---|---|---|---|---|---|---|",
        ]
        group_ids = {ref: g.group_id for g in result.assembly.groups for ref in g.members}
        lines += [
            f"| `{p.reference_review_id}` | `{p.reference_decision}` | "
            f"`{p.proposed_decision or 'MISSING_CANDIDATE'}` | "
            f"`{p.reference_task_relation}` | "
            f"`{p.proposed_task_relation or 'MISSING_CANDIDATE'}` | "
            f"{', '.join(p.issues) or 'Khớp các trường đã so sánh'} | "
            f"[Trái](index.html#{group_ids[p.left]}) / [Phải](index.html#{group_ids[p.right]}) |"
            for p in comparison.pairs
        ]
        (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _dump(output / "run.json", run)
    _dump(output / "checksums.json", {p.name: _sha(p) for p in sorted(output.iterdir())})
    print(json.dumps({"workflow_counts": counts, "development_diagnostics": diagnostics}))


if __name__ == "__main__":
    main()
