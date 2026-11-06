"""Collect 100 unique notices across HCMUS, UIT and UEH into a new private run."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from smartnotice.collectors.crawl import crawl_web, validate_run_id
from smartnotice.collectors.dataset import validate_corpus
from smartnotice.collectors.web import WebCollector
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.preprocessing.pipeline import prepare


def main() -> int:
    """Collect quotas 40/30/30, preserving per-source evidence and combined outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--limits", type=int, nargs=3, default=[40, 30, 30], metavar=("HCMUS", "UIT", "UEH")
    )
    parser.add_argument("--output-root", type=Path, default=Path("data/raw/crawls"))
    args = parser.parse_args()
    if any(n < 1 for n in args.limits) or sum(args.limits) != 100:
        parser.error("The three source limits must be positive and sum to 100")
    root = args.output_root / validate_run_id(args.run_id)
    root.mkdir(parents=True, exist_ok=False)
    indices, notices, errors = [], [], {}
    sources = ["hcmus-student", "uit-student", "ueh-student"]

    def collect(pair):
        source, quota = pair
        run = root / source
        error = None
        print(f"Collecting {source}: target {quota}", flush=True)
        with httpx.Client(timeout=45) as client:
            try:
                crawl_web(
                    WebCollector(client, interval=2),
                    run,
                    source=source,
                    limit=quota,
                    max_candidates=300,
                    max_pages=40,
                )
            except (ValueError, OSError, httpx.HTTPError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                print(f"{source}: {error}", flush=True)
                if (run / "raw/manifest.jsonl").exists():
                    prepare(run / "raw/manifest.jsonl", run / "prepared/notices.jsonl")
        return source, error

    # Each worker owns a distinct origin and retains its own robots and spacing state.
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(collect, zip(sources, args.limits, strict=True)))
    for source, error in results:
        if error:
            errors[source] = error
        run = root / source
        if (run / "index.jsonl").exists():
            rows = read_jsonl(run / "index.jsonl")
            for row in rows:
                for field in ["raw_path", "snapshot_path"]:
                    row[field] = f"{source}/{row[field]}"
            indices.extend(rows)
            notices.extend(read_jsonl(run / "prepared/notices.jsonl"))
            print(f"{source}: {len(rows)} accepted", flush=True)
    unique = {}
    for row in indices:
        unique.setdefault(row["prepared_text_sha256"], row)
    indices = list(unique.values())
    ids = {row["doc_id"] for row in indices}
    by_id = {row["doc_id"]: row for row in notices}
    notices = [by_id[row["doc_id"]] for row in indices]
    if len(ids) != len(notices):
        raise ValueError("Conflicting document identities in combined output")
    write_jsonl(root / "index.jsonl", indices)
    write_jsonl(root / "prepared/notices.jsonl", notices)
    counts = {
        name: sum(r["institution"] == name for r in indices) for name in ["HCMUS", "UIT", "UEH"]
    }
    expected_counts = dict(zip(["HCMUS", "UIT", "UEH"], args.limits, strict=True))
    source_complete = all(
        json.loads((root / source / "summary.json").read_text(encoding="utf-8"))["complete"]
        for source in sources
    )
    summary = {
        "target": 100,
        "source_targets": dict(zip(sources, args.limits, strict=True)),
        "accepted": len(indices),
        "institutions": counts,
        "complete": len(indices) == 100
        and counts == expected_counts
        and source_complete
        and not errors,
        "errors": errors,
        "privacy_review_required": True,
        "date_review_required": True,
        "content_review_required": True,
    }
    if summary["complete"]:
        try:
            validation = validate_corpus(root, expected_counts)
            (root / "validation.json").write_text(
                json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except ValueError as exc:
            summary["complete"] = False
            summary["errors"]["validation"] = str(exc)
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
