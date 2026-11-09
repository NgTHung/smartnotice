"""Build private provisional event/task groups from attributed pair reviews."""

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.event_groups import build_event_groups
from smartnotice.schemas import Annotation, GroupingReview, Notice, TimeBoundaryReview


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path, model: type) -> list:
    output = []
    for number, value in enumerate(read_jsonl(path), 1):
        try:
            output.append(model.model_validate(value))
        except ValueError:
            raise ValueError(f"Invalid {model.__name__} on line {number}") from None
    return output


def _dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Validate before creating a new private output directory; refuse overwrites.

    Source files, human approvals and evaluation splits remain unchanged. All
    groups require review, regardless of the input review author's kind.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--time-boundaries", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = args.output_dir.resolve()
    if not any(output.is_relative_to(root / p) for p in ["data/processed", "reports/generated"]):
        raise ValueError("Output must stay in data/processed or reports/generated")
    if output.exists():
        raise ValueError("Output already exists; choose a new directory")
    paths = [args.notices, args.annotations, args.reviews]
    if args.time_boundaries:
        paths.append(args.time_boundaries)
    before = {p.as_posix(): _sha(p) for p in paths}
    result = build_event_groups(
        _read(args.notices, Notice),
        _read(args.annotations, Annotation),
        _read(args.reviews, GroupingReview),
        _read(args.time_boundaries, TimeBoundaryReview) if args.time_boundaries else [],
    )
    if any(_sha(p) != before[p.as_posix()] for p in paths):
        raise ValueError("Input changed during assembly")
    code = [
        Path(__file__),
        Path("src/labeling/event_groups.py"),
        Path("src/schemas.py"),
        Path("uv.lock"),
    ]
    run = {
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": result.schema_version,
        "source_sha256": before,
        "code_sha256": {p.as_posix(): _sha(p) for p in code},
        "environment": {"python": platform.python_version(), "system": platform.system()},
        "mentions": len(result.mentions),
        "groups": len(result.groups),
        "tasks": sum(len(g.tasks) for g in result.groups),
        "reviews": len(result.reviews),
        "applied_updates": sum(u.applied for u in result.updates),
        "conflicts": len(result.conflicts),
        "reviewer_kinds": sorted({r.author.reviewer_kind for r in result.reviews}),
        "quality_measured": False,
        "privacy_approval_created": False,
        "split_assignments_changed": False,
        "randomness": None,
    }
    output.mkdir(parents=True)
    _dump(output / "assembly.json", result.model_dump(mode="json"))
    write_jsonl(output / "groups.jsonl", [g.model_dump(mode="json") for g in result.groups])
    write_jsonl(output / "conflicts.jsonl", [c.model_dump(mode="json") for c in result.conflicts])
    _dump(output / "run.json", run)
    worksheet = [
        "# Nhóm sự kiện và đầu việc đề xuất",
        "",
        "Đầu ra cần duyệt; tác giả của từng quyết định nằm trong assembly.json. "
        "Không có clearance riêng tư được tạo.",
        "",
    ]
    for group in result.groups:
        worksheet += [
            f"## Nhóm `{group.group_id}`",
            "",
            f"{len(group.members)} lần nhắc, {len(group.document_ids)} tài liệu, "
            f"{len(group.tasks)} đầu việc/phiên.",
            "",
        ]
        for task in group.tasks:
            worksheet += [
                f"### Đầu việc/phiên `{task.task_id}`",
                "",
                ", ".join(f"`{r}`" for r in task.members),
                "",
            ]
            by_id = {f.fact_id: f for f in task.facts}
            for field, ids in task.active_values.items():
                if field in {"START", "END", "DEADLINE", "EVENT_TIME", "LOCATION", "STATUS"}:
                    worksheet += [f"- {field}: " + " / ".join(by_id[fid].quote.text for fid in ids)]
            worksheet.append("")
    worksheet += ["## Mâu thuẫn cần xem", ""]
    worksheet += [
        f"- `{c.kind}`: {', '.join(c.members)}; trường {c.field or 'identity'}."
        for c in result.conflicts
    ]
    (output / "review_groups.md").write_text("\n".join(worksheet) + "\n", encoding="utf-8")
    _dump(output / "checksums.json", {p.name: _sha(p) for p in sorted(output.iterdir())})
    print(
        json.dumps(
            {
                key: run[key]
                for key in [
                    "mentions",
                    "groups",
                    "tasks",
                    "reviews",
                    "applied_updates",
                    "conflicts",
                ]
            }
        )
    )


if __name__ == "__main__":
    main()
