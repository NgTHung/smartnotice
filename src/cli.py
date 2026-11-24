"""Expose reproducible collection, preparation, and annotation commands."""

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

import httpx
from pydantic import ValidationError
from smartnotice.collectors.local import collect_emails, save_source
from smartnotice.collectors.web import WebCollector
from smartnotice.demo import run_demo
from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.llm import (
    has_privacy_clearance,
    has_provider_approval,
    json_sha256,
    privacy_review_queue,
    require_provider_approval,
)
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.labeling.providers import configured_model, load_local_env
from smartnotice.labeling.studio import (
    export_tasks,
    import_reviewed_tasks,
    import_tasks,
)
from smartnotice.labeling.validation import validate_annotation
from smartnotice.labeling.workflow import suggest_tasks
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.privacy_audit import audit_email_policy
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
    email = commands.add_parser("collect-email", help="Import consented .eml files or a directory")
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
    prep = commands.add_parser("prepare", help="Parse, redact, and segment a manifest")
    prep.add_argument("--manifest", type=Path, default=Path("data/raw/manifest.jsonl"))
    prep.add_argument("--output", type=Path, default=Path("data/interim/notices.jsonl"))
    prep.add_argument("--privacy-rules", type=Path, help="Private JSON identifier/contact lists")
    prep.add_argument("--email-policy", choices=["all", "legacy"], default="all")
    prep.add_argument(
        "--errors-output",
        type=Path,
        help="Continue after source errors and write rejected-source JSONL here",
    )
    audit = commands.add_parser(
        "audit-email-policy", help="Write a private legacy email review list"
    )
    audit.add_argument("inputs", nargs="+", type=Path)
    audit.add_argument("--privacy-rules", type=Path)
    audit.add_argument("--output-dir", type=Path, default=Path("reports/generated/email-policy"))
    suggest = commands.add_parser("suggest-labels", help="Draft review tasks with an LLM")
    suggest.add_argument("--notices", type=Path, default=Path("data/interim/notices.jsonl"))
    suggest.add_argument(
        "--doc-id", action="append", help="Select an ID; repeat for several notices"
    )
    suggest.add_argument(
        "--selection",
        type=Path,
        help="JSONL with doc_id rows, such as a split file or failure ledger",
    )
    suggest.add_argument("--split", help="Use only --selection rows with this split value")
    suggest.add_argument(
        "--approved-only",
        action="store_true",
        help="Skip selected real notices without approval for this provider",
    )
    suggest.add_argument("--provider", choices=["gemini", "featherless"], required=True)
    suggest.add_argument("--model", help="Override GEMINI_MODEL or FEATHERLESS_MODEL")
    suggest.add_argument(
        "--approvals", type=Path, default=Path("data/annotations/provider_approvals.jsonl")
    )
    suggest.add_argument("--output", type=Path, required=True)
    suggest.add_argument("--errors-output", type=Path, help="Default: OUTPUT.errors.jsonl")
    suggest.add_argument(
        "--dry-run", action="store_true", help="Validate selection without API calls"
    )
    reviewed = commands.add_parser(
        "import-reviewed-labels", help="Import human-checked predictions and a review log"
    )
    reviewed.add_argument("--notices", type=Path, default=Path("data/interim/notices.jsonl"))
    reviewed.add_argument("--input", type=Path, required=True)
    reviewed.add_argument("--predictions", type=Path, required=True, help="Original saved tasks")
    reviewed.add_argument("--output", type=Path, required=True)
    reviewed.add_argument("--review-log", type=Path, required=True)
    profile_parser = commands.add_parser(
        "generate-profiles", help="Design seeded synthetic profiles from audience constraints"
    )
    profile_parser.add_argument("--annotations", type=Path, required=True)
    profile_parser.add_argument(
        "--output", type=Path, default=Path("data/processed/profiles.jsonl")
    )
    profile_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    train = commands.add_parser(
        "train-applicability", help="Train and score models on grouped applicability pairs"
    )
    train.add_argument("--model", choices=["lightgbm", "logreg"], default="lightgbm")
    train.add_argument("--pairs", type=Path, required=True)
    train.add_argument("--notices", type=Path, required=True)
    train.add_argument("--assignments", type=Path, required=True)
    train.add_argument("--audience-source", choices=["human", "predicted", "none"], required=True)
    train.add_argument("--audience-annotations", type=Path)
    train.add_argument("--train-sources", nargs="+", choices=["email", "web"])
    train.add_argument("--learning-curve", nargs="+", type=float, metavar="FRACTION")
    train.add_argument("--seeds", nargs="+", type=int, metavar="SEED")
    train.add_argument("--folds", type=int)
    train.add_argument("--tfidf", action=argparse.BooleanOptionalAction, default=True)
    train.add_argument("--no-source-feature", dest="source_feature", action="store_false")
    train.add_argument(
        "--params", type=Path, help="JSON object of parameters for the selected model"
    )
    train.add_argument("--param-grid", type=Path, help="JSON list of parameter override objects")
    train.add_argument("--weighting", choices=["event", "pair"], default="event")
    train.add_argument("--fit-final", action="store_true")
    train.add_argument("--output-dir", type=Path, help="New run directory")
    train.add_argument("--lexicon", type=Path, help="Override config/applicability_lexicon.json")
    train.add_argument("--allow-synthetic", action="store_true")
    for name in [
        "split",
        "quality",
        "export-tasks",
        "privacy-review-queue",
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
                "--approvals", type=Path, default=Path("data/annotations/provider_approvals.jsonl")
            )
            command.add_argument(
                "--output", type=Path, default=Path("data/annotations/label_studio_tasks.json")
            )
        elif name == "privacy-review-queue":
            command.add_argument(
                "--approvals", type=Path, default=Path("data/annotations/provider_approvals.jsonl")
            )
            command.add_argument(
                "--output", type=Path, default=Path("data/interim/privacy_review_queue.jsonl")
            )
        elif name == "import-labels":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--annotations", type=Path, required=True)
            if name == "build-pairs":
                command.add_argument("--profiles", type=Path, required=True)
                command.add_argument(
                    "--assume-all-students-without-audience",
                    action="store_true",
                    help="Record an all-learners default for events without AUDIENCE",
                )
                command.add_argument(
                    "--output", type=Path, default=Path("data/processed/applicability.jsonl")
                )
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            print(json.dumps(run_demo(args.root), ensure_ascii=False, indent=2))
        elif args.command == "collect-email":
            rows = collect_emails([args.path], args.raw_dir, args.consent_ref, args.group_id)
            print(rows[0]["path"] if len(rows) == 1 else f"Imported {len(rows)} email sources")
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
        elif args.command == "prepare":
            notices = prepare(
                args.manifest,
                args.output,
                privacy_rules=args.privacy_rules,
                email_policy=args.email_policy,
                errors_output=args.errors_output,
            )
            print(f"Prepared {len(notices)} notices: {args.output}")
            if args.errors_output:
                failed_count = len(read_jsonl(args.errors_output))
                print(f"Rejected {failed_count} sources: {args.errors_output}")
                if failed_count:
                    parser.exit(1, "smartnotice: review rejected sources before using this batch\n")
        elif args.command == "audit-email-policy":
            report = audit_email_policy(
                args.inputs, args.output_dir, privacy_rules=args.privacy_rules
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "suggest-labels":
            errors_output = args.errors_output or args.output.with_suffix(".errors.jsonl")
            if (
                args.output.resolve() == errors_output.resolve()
                or args.output.exists()
                or errors_output.exists()
            ):
                raise ValueError("Prediction and error outputs must be distinct new files")
            notices = _load(args.notices, Notice)
            if len({n.doc_id for n in notices}) != len(notices):
                raise ValueError("Notice document IDs must be unique")
            if args.split and not args.selection:
                raise ValueError("--split requires a --selection file")
            requested = set(args.doc_id or [])
            if args.selection:
                requested |= {
                    row["doc_id"]
                    for row in read_jsonl(args.selection)
                    if args.split is None or row.get("split") == args.split
                }
            elif not requested:
                requested = {n.doc_id for n in notices}
            selected = [notice for notice in notices if notice.doc_id in requested]
            if not selected or requested != {n.doc_id for n in selected}:
                raise ValueError("Selection contains no notices or unknown document IDs")
            approvals = read_jsonl(args.approvals) if args.approvals.exists() else []
            if args.approved_only:
                count = len(selected)
                selected = [
                    notice
                    for notice in selected
                    if has_provider_approval(notice, args.provider, approvals)
                ]
                requested = {notice.doc_id for notice in selected}
                print(f"Skipped {count - len(selected)} unapproved notices", file=sys.stderr)
                if not selected:
                    raise ValueError("No selected notices are approved for this provider")
            for notice in selected:
                require_provider_approval(notice, args.provider, approvals)
            load_local_env()
            model = args.model or configured_model(args.provider)
            if args.dry_run:
                print(
                    json.dumps(
                        {"provider": args.provider, "model": model, "doc_ids": sorted(requested)}
                    )
                )
                return
            tasks, failures = suggest_tasks(
                selected, provider=args.provider, model=model, approvals=approvals
            )
            _json(args.output, tasks)
            write_jsonl(errors_output, failures)
            print(f"Wrote {len(tasks)} predictions and {len(failures)} failures: {args.output}")
            if failures:
                parser.exit(1, f"smartnotice: review failed attempts in {errors_output}\n")
        elif args.command == "import-reviewed-labels":
            if (
                args.output.resolve() == args.review_log.resolve()
                or args.output.exists()
                or args.review_log.exists()
            ):
                raise ValueError("Review outputs must be distinct new files")
            notices = _load(args.notices, Notice)
            tasks = json.loads(args.input.read_text(encoding="utf-8-sig"))
            predictions = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
            annotations, reviews = import_reviewed_tasks(tasks, notices, predictions)
            write_jsonl(args.output, [a.model_dump(mode="json") for a in annotations])
            write_jsonl(args.review_log, reviews)
            print(
                f"Imported {len(annotations)} reviewed annotations; logged {len(reviews)} decisions"
            )
        elif args.command == "train-applicability":
            if args.output_dir is not None and args.output_dir.exists():
                raise ValueError(f"Applicability run directory already exists: {args.output_dir}")
            from smartnotice.modeling.applicability_training import TrainingConfig, run_training
            from smartnotice.modeling.lexicon import DEFAULT_LEXICON_PATH

            option_names = (
                "model",
                "audience_source",
                "train_sources",
                "learning_curve",
                "seeds",
                "folds",
                "tfidf",
                "source_feature",
                "weighting",
                "fit_final",
                "allow_synthetic",
            )
            options = {
                name: getattr(args, name)
                for name in option_names
                if getattr(args, name) is not None
            }
            config_inputs = {}
            for name in ("params", "param_grid"):
                if path := getattr(args, name):
                    content = path.read_bytes()
                    try:
                        options[name] = json.loads(content.decode("utf-8-sig"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        raise ValueError(f"{path}: expected valid UTF-8 JSON") from None
                    config_inputs[name] = {"path": str(path), "sha256": sha256(content).hexdigest()}
            config = TrainingConfig.model_validate(options)
            output = run_training(
                config,
                pairs_path=args.pairs,
                notices_path=args.notices,
                assignments_path=args.assignments,
                annotations_path=args.audience_annotations,
                lexicon_path=args.lexicon or DEFAULT_LEXICON_PATH,
                output_dir=args.output_dir,
                config_inputs=config_inputs,
            )
            print(output)
        elif args.command == "generate-profiles":
            annotations = _load(args.annotations, Annotation)
            constraints = [c for a in annotations for c in a.audience_constraints]
            designed = [
                p.model_dump(mode="json") for p in generate_profiles(constraints, args.seed)
            ]
            record = {
                "seed": args.seed,
                "annotations_sha256": json_sha256([a.model_dump(mode="json") for a in annotations]),
                "constraint_count": len(constraints),
                "profile_count": len(designed),
                "profile_set_sha256": json_sha256(designed),
            }
            write_jsonl(args.output, designed)
            _json(args.output.with_suffix(".record.json"), record)
            print(f"Generated {len(designed)} profiles: {args.output}")
        else:
            notices = _load(args.notices, Notice)
            if args.command == "split":
                write_jsonl(args.output, split_documents(notices, args.seed, args.similarity))
            elif args.command == "quality":
                report = quality_summary(notices, read_jsonl(args.splits))
                _json(args.output, report)
                print(json.dumps(report, ensure_ascii=False, indent=2))
            elif args.command == "export-tasks":
                approvals = read_jsonl(args.approvals) if args.approvals.exists() else []
                cleared = [n for n in notices if has_privacy_clearance(n, approvals)]
                if not cleared:
                    raise ValueError("No privacy-cleared notices; run privacy-review-queue")
                _json(args.output, export_tasks(cleared))
                print(
                    f"Exported {len(cleared)} tasks; "
                    f"held {len(notices) - len(cleared)} without privacy review: {args.output}"
                )
            elif args.command == "privacy-review-queue":
                if args.output.resolve() in {args.approvals.resolve(), args.notices.resolve()}:
                    raise ValueError("The review queue must not replace its inputs")
                approvals = read_jsonl(args.approvals) if args.approvals.exists() else []
                queue = privacy_review_queue(notices, approvals)
                write_jsonl(args.output, [item.model_dump(mode="json") for item in queue])
                print(f"{len(queue)} of {len(notices)} notices await review: {args.output}")
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
                    write_jsonl(
                        args.output,
                        build_pairs(
                            notices,
                            annotations,
                            profiles,
                            assume_all_students_without_audience=args.assume_all_students_without_audience,
                        ),
                    )
    except ValidationError:
        parser.exit(1, "smartnotice: schema validation failed; inspect the input locally\n")
    except (ValueError, KeyError, OSError, httpx.HTTPError) as exc:
        parser.exit(1, f"smartnotice: {exc}\n")
