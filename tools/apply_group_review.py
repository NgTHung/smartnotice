"""Apply exported group notes and an explicit resolution plan to a new snapshot."""

import argparse
import hashlib
import json
import platform
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.event_groups import assembly_fingerprint, build_event_groups
from smartnotice.labeling.group_feedback import apply_group_feedback
from smartnotice.labeling.group_viewer import render_group_review
from smartnotice.schemas import (
    Annotation,
    EventGroupAssembly,
    GroupDisplayLabels,
    GroupFeedbackPlan,
    LocalGroupReviewNotes,
    Notice,
    ReviewAuthor,
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
    """Validate a viewed snapshot and all resolutions before writing a new one.

    Preserve original notes and source bytes. Accept, split or explicitly merge
    existing mentions; added content requires a separate annotation migration.
    Display names quote member sources and do not add student obligations.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["assembly", "notices", "annotations", "notes", "plan", "output-dir"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--applied-at", type=datetime.fromisoformat)
    args = parser.parse_args()
    root, output = Path.cwd().resolve(), args.output_dir.resolve()
    if not any(output.is_relative_to(root / p) for p in ["data/processed", "reports/generated"]):
        raise ValueError("Output must stay in data/processed or reports/generated")
    if output.exists():
        raise ValueError("Output already exists; choose a new directory")
    template = Path(__file__).parent / "templates/group_review.html.template"
    inputs = [args.assembly, args.notices, args.annotations, args.notes, args.plan]
    code = [
        Path(__file__),
        Path("src/schemas.py"),
        Path("src/labeling/group_feedback.py"),
        Path("src/labeling/event_groups.py"),
        Path("src/labeling/group_viewer.py"),
        Path("src/labeling/validation.py"),
        Path("src/labeling/llm.py"),
        template,
        Path("uv.lock"),
    ]
    before = {p.as_posix(): _sha(p) for p in inputs + code}
    assembly = EventGroupAssembly.model_validate_json(args.assembly.read_bytes())
    notes = LocalGroupReviewNotes.model_validate_json(args.notes.read_bytes())
    plan = GroupFeedbackPlan.model_validate_json(args.plan.read_bytes())
    if any(r.mode == "SEPARATE_CONTENT" for r in plan.resolutions):
        raise ValueError("Added content requires a separate validated annotation migration")
    notices, annotations = _read(args.notices, Notice), _read(args.annotations, Annotation)
    checked = build_event_groups(notices, annotations, assembly.reviews, assembly.time_boundaries)
    if checked != assembly:
        raise ValueError("Viewed assembly does not reproduce from supplied source snapshots")
    author = ReviewAuthor(
        reviewer_id="ai_assistant",
        reviewer_kind="ai_assistant",
        reviewed_at=args.applied_at or datetime.now(UTC),
    )
    feedback = apply_group_feedback(
        assembly,
        notes,
        plan.resolutions,
        notes_sha256=before[args.notes.as_posix()],
        application_author=author,
        merges=plan.merges,
    )
    updated = build_event_groups(notices, annotations, feedback.reviews, assembly.time_boundaries)
    labels = GroupDisplayLabels(
        assembly_fingerprint=assembly_fingerprint(updated), labels=plan.display_labels
    )
    html = render_group_review(
        updated, notices, template.read_text(encoding="utf-8"), feedback=feedback, labels=labels
    )
    if any(_sha(p) != before[p.as_posix()] for p in inputs + code):
        raise ValueError("Input or implementation changed during review application")
    counts = {
        "notes": len(notes.entries),
        "source_statuses": dict(Counter(n.status for n in notes.entries)),
        "applications": dict(Counter(a.outcome for a in feedback.applications)),
        "mentions": len(updated.mentions),
        "groups": len(updated.groups),
        "tasks": sum(len(g.tasks) for g in updated.groups),
        "applied_updates": sum(u.applied for u in updated.updates),
        "conflicts": len(updated.conflicts),
        "display_labels": len(labels.labels),
    }
    run = {
        "applied_at": author.reviewed_at.isoformat(),
        "source_sha256": before,
        "source_assembly_fingerprint": assembly_fingerprint(assembly),
        "result_assembly_fingerprint": assembly_fingerprint(updated),
        "environment": {"python": platform.python_version(), "system": platform.system()},
        "workflow_counts": counts,
        "label_origin": "assistant_application_of_user_group_feedback",
        "independent_human_pair_reviews_created": False,
        "privacy_approval_created": False,
        "split_assignments_changed": False,
        "randomness": None,
    }
    output.mkdir(parents=True)
    (output / "source_notes.json").write_bytes(args.notes.read_bytes())
    (output / "resolution_plan.json").write_bytes(args.plan.read_bytes())
    _dump(output / "feedback_application.json", feedback.model_dump(mode="json"))
    _dump(output / "assembly.json", updated.model_dump(mode="json"))
    _dump(output / "display_labels.json", labels.model_dump(mode="json"))
    write_jsonl(
        output / "pair_reviews.jsonl", [r.model_dump(mode="json") for r in feedback.reviews]
    )
    write_jsonl(output / "groups.jsonl", [g.model_dump(mode="json") for g in updated.groups])
    write_jsonl(output / "conflicts.jsonl", [c.model_dump(mode="json") for c in updated.conflicts])
    (output / "index.html").write_text(html, encoding="utf-8")
    _dump(output / "run.json", run)
    _dump(output / "checksums.json", {p.name: _sha(p) for p in sorted(output.iterdir())})
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
