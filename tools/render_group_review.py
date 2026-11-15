"""Export one standalone local HTML page for reviewing grouped source emails."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from smartnotice.io import read_jsonl
from smartnotice.labeling.group_viewer import render_group_review
from smartnotice.schemas import EventGroupAssembly, GroupDisplayLabels, GroupFeedbackResult, Notice


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """Validate sources and create a new private HTML artifact with provenance.

    Run from the repository root. Output must stay in reports/generated; existing
    output files are refused. No source, review record or approval is modified.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feedback", type=Path, action="append", default=[])
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if (
        not output.is_relative_to(Path.cwd().resolve() / "reports/generated")
        or output.suffix.lower() != ".html"
    ):
        raise ValueError("Output must be an HTML file inside reports/generated")
    metadata = output.with_suffix(".metadata.json")
    if output.exists() or metadata.exists():
        raise ValueError("Output already exists; choose a new file")
    template = Path(__file__).parent / "templates/group_review.html.template"
    inputs = [args.assembly, args.notices, template, Path("src/labeling/group_viewer.py")]
    inputs.extend(args.feedback)
    if args.labels:
        inputs.append(args.labels)
    before = {p.as_posix(): _sha(p) for p in inputs}
    assembly = EventGroupAssembly.model_validate_json(args.assembly.read_text(encoding="utf-8"))
    notices = [Notice.model_validate(row) for row in read_jsonl(args.notices)]
    feedback = [
        GroupFeedbackResult.model_validate_json(path.read_text(encoding="utf-8"))
        for path in args.feedback
    ]
    html = render_group_review(
        assembly,
        notices,
        template.read_text(encoding="utf-8"),
        feedback=feedback,
        labels=GroupDisplayLabels.model_validate_json(args.labels.read_bytes())
        if args.labels
        else None,
    )
    if any(_sha(p) != before[p.as_posix()] for p in inputs):
        raise ValueError("Input changed during rendering")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    run = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_sha256": before,
        "html_sha256": _sha(output),
        "groups": len(assembly.groups),
        "mentions": len(assembly.mentions),
        "human_approval_created": False,
        "privacy_approval_created": False,
        "hosted": False,
    }
    metadata.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "groups": len(assembly.groups),
                "mentions": len(assembly.mentions),
                "output": output.as_posix(),
            }
        )
    )


if __name__ == "__main__":
    main()
