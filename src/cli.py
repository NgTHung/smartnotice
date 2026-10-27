"""Expose reproducible collection, preparation, and annotation commands."""

import argparse
import json
import sys
from pathlib import Path

import httpx
from smartnotice.collectors.crawl import crawl_web, validate_run_id
from smartnotice.collectors.local import collect_email, save_source
from smartnotice.collectors.web import WebCollector
from smartnotice.demo import run_demo
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.studio import export_tasks, import_tasks
from smartnotice.labeling.validation import validate_annotation
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.split import DEFAULT_SEED, split_documents
from smartnotice.quality import quality_summary
from smartnotice.schemas import Annotation, Notice, Profile


def _load(path: Path, schema):
    return [schema.model_validate(row) for row in read_jsonl(path)]


def _json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    """Run one stage; failures return a nonzero exit code and a concise reason."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the offline synthetic example")
    demo.add_argument("--root", type=Path, default=Path.cwd())
    email = commands.add_parser("collect-email", help="Import a voluntarily supplied .eml")
    email.add_argument("path", type=Path)
    email.add_argument("--consent-ref", required=True)
    email.add_argument("--group-id")
    email.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    web = commands.add_parser("collect-web", help="Fetch one public HTML URL")
    web.add_argument("url")
    web.add_argument("--selector", required=True, help="CSS selector for the notice body")
    web.add_argument("--reference-date", help="Verified publication date, YYYY-MM-DD")
    web.add_argument("--group-id")
    web.add_argument("--domain-holdout", action="store_true")
    web.add_argument("--interval", type=float, default=2.0)
    web.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    crawl = commands.add_parser("crawl-web", help="Discover and collect a bounded HCMUS pilot")
    crawl.add_argument("--source", choices=["hcmus-student"], default="hcmus-student")
    crawl.add_argument("--run-id", required=True, help="New run folder name; letters/digits/_/-")
    crawl.add_argument("--output-root", type=Path, default=Path("data/raw/crawls"))
    crawl.add_argument("--limit", type=int, default=10)
    crawl.add_argument("--max-candidates", type=int, default=40)
    crawl.add_argument("--min-chars", type=int, default=100, help="Flag shorter text for review")
    crawl.add_argument("--interval", type=float, default=2.0, help="Seconds between requests, >=1")
    crawl.add_argument("--domain-holdout", action="store_true")
    crawl.add_argument("--group-id")
    prep = commands.add_parser("prepare", help="Parse, redact, and segment a manifest")
    prep.add_argument("--manifest", type=Path, default=Path("data/raw/manifest.jsonl"))
    prep.add_argument("--output", type=Path, default=Path("data/interim/notices.jsonl"))
    for name in [
        "split",
        "quality",
        "export-tasks",
        "import-labels",
        "validate-labels",
        "build-pairs",
    ]:
        command = commands.add_parser(name)
        command.add_argument("--notices", type=Path, default=Path("data/interim/notices.jsonl"))
        if name == "split":
            command.add_argument("--output", type=Path, default=Path("data/processed/splits.jsonl"))
            command.add_argument("--seed", type=int, default=DEFAULT_SEED)
            command.add_argument("--similarity", type=float, default=0.9)
        elif name == "quality":
            command.add_argument("--splits", type=Path, default=Path("data/processed/splits.jsonl"))
            command.add_argument(
                "--output", type=Path, default=Path("reports/generated/quality.json")
            )
        elif name == "export-tasks":
            command.add_argument(
                "--output", type=Path, default=Path("data/annotations/label_studio_tasks.json")
            )
        elif name == "import-labels":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--annotations", type=Path, required=True)
            if name == "build-pairs":
                command.add_argument("--profiles", type=Path, required=True)
                command.add_argument(
                    "--output", type=Path, default=Path("data/processed/applicability.jsonl")
                )
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            print(json.dumps(run_demo(args.root), ensure_ascii=False, indent=2))
        elif args.command == "collect-email":
            row = collect_email(args.path, args.raw_dir, args.consent_ref, args.group_id)
            print(row["path"])
        elif args.command == "collect-web":
            if args.reference_date:
                from datetime import date

                date.fromisoformat(args.reference_date)
            with httpx.Client(timeout=30) as client:
                raw, url = WebCollector(client, args.interval).fetch(args.url)
            row = save_source(
                raw,
                args.raw_dir,
                "web",
                url=url,
                selector=args.selector,
                reference_date=args.reference_date,
                group_id=args.group_id,
                domain_holdout=args.domain_holdout,
            )
            print(row["path"])
        elif args.command == "crawl-web":
            run_id = validate_run_id(args.run_id)
            with httpx.Client(timeout=30) as client:
                result = crawl_web(
                    WebCollector(client, args.interval),
                    args.output_root / run_id,
                    limit=args.limit,
                    max_candidates=args.max_candidates,
                    min_chars=args.min_chars,
                    domain_holdout=args.domain_holdout,
                    group_id=args.group_id,
                )
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
            if not result.complete:
                parser.exit(
                    2, "smartnotice: candidate budget exhausted before reaching the target\n"
                )
        elif args.command == "prepare":
            print(f"Prepared {len(prepare(args.manifest, args.output))} notices: {args.output}")
        else:
            notices = _load(args.notices, Notice)
            if args.command == "split":
                write_jsonl(args.output, split_documents(notices, args.seed, args.similarity))
            elif args.command == "quality":
                report = quality_summary(notices, read_jsonl(args.splits))
                _json(args.output, report)
                print(json.dumps(report, ensure_ascii=False, indent=2))
            elif args.command == "export-tasks":
                _json(args.output, export_tasks(notices))
            elif args.command == "import-labels":
                tasks = json.loads(args.input.read_text(encoding="utf-8-sig"))
                annotations = import_tasks(tasks, notices)
                write_jsonl(args.output, [a.model_dump(mode="json") for a in annotations])
            else:
                annotations = _load(args.annotations, Annotation)
                documents = {notice.doc_id: notice for notice in notices}
                for annotation in annotations:
                    validate_annotation(annotation, documents[annotation.doc_id])
                if args.command == "validate-labels":
                    print(f"Validated {len(annotations)} annotations")
                else:
                    profiles = _load(args.profiles, Profile)
                    write_jsonl(args.output, build_pairs(notices, annotations, profiles))
    except KeyboardInterrupt:
        parser.exit(
            130, "smartnotice: interrupted; inspect the run directory before starting again\n"
        )
    except (ValueError, KeyError, OSError, httpx.HTTPError) as exc:
        parser.exit(1, f"smartnotice: {exc}\n")
