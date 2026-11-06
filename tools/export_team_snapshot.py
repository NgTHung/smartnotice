"""Export the checked 40/30/30 corpus as prepared text for team use."""

import argparse
import json
from pathlib import Path

from smartnotice.collectors.dataset import export_team_snapshot


def main() -> int:
    """Write shared notices and hash mappings while keeping human review pending."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_team_snapshot(args.run_dir, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
