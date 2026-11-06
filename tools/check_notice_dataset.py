"""Validate a 40/30/30 local crawl or its shared prepared snapshot."""

import argparse
import json
from pathlib import Path

from smartnotice.collectors.dataset import export_catalog, validate_corpus, validate_team_snapshot


def main() -> int:
    """Validate the complete corpus; retain personal-pattern findings only locally."""
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--run-dir", type=Path)
    inputs.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--catalog-dir", type=Path)
    args = parser.parse_args()
    if args.snapshot_dir:
        if args.catalog_dir:
            parser.error("--catalog-dir requires --run-dir")
        print(json.dumps(validate_team_snapshot(args.snapshot_dir), ensure_ascii=False, indent=2))
        return 0
    counts = {"HCMUS": 40, "UIT": 30, "UEH": 30}
    report = (
        export_catalog(args.run_dir, args.catalog_dir, counts)
        if args.catalog_dir
        else validate_corpus(args.run_dir, counts)
    )
    (args.run_dir / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    safe_report = {key: value for key, value in report.items() if key != "privacy_pattern_findings"}
    safe_report["documents_with_privacy_pattern_findings"] = len(report["privacy_pattern_findings"])
    if args.catalog_dir:
        (args.catalog_dir / "validation.json").write_text(
            json.dumps(safe_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(safe_report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
