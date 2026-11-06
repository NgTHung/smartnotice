"""Rebuild catalogued notice text locally without adding real article bodies to Git."""

import argparse
from pathlib import Path

import httpx
from smartnotice.collectors.crawl import validate_run_id
from smartnotice.collectors.dataset import fetch_catalog
from smartnotice.collectors.web import WebCollector


def main() -> int:
    """Recreate a source catalog under a new ignored local crawl directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/raw/crawls"))
    args = parser.parse_args()
    with httpx.Client(timeout=45) as client:
        count = fetch_catalog(
            WebCollector(client), args.catalog, args.output_root / validate_run_id(args.run_id)
        )
    print(f"Prepared {count} matching notice texts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
