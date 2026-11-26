"""Run the zero-shot decision-model pilot on the train/validation pool.

Subcommands, run from the repository root:

    uv run python tools/decision_reference_pilot.py sample --split-dir DIR
    uv run python tools/decision_reference_pilot.py run --split-dir DIR --provider jev
    uv run python tools/decision_reference_pilot.py score

``sample`` designs deduplicated profiles from train/validation constraints,
derives silver labels with ``build_pairs`` (missing audiences stay UNCLEAR),
and writes the stratified sample. ``run`` reads the API key from the provider's
environment variable and sends one request per event and audience mode.
``score`` writes per-provider metrics and cross-provider agreement. Outputs go
to ``reports/generated/decision-reference-pilot/`` and contain identifiers,
labels, answers, and hashes, never notice text. Results are vendor model
predictions scored against rule-derived silver labels.
"""

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from random import Random

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.llm import json_sha256
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.modeling.applicability_features import build_inputs
from smartnotice.modeling.decision_reference import (
    INSTRUCTIONS_SHA256,
    INSTRUCTIONS_VERSION,
    PROVIDERS,
    agreement,
    build_request,
    run_requests,
    score_pilot,
    select_pilot,
)
from smartnotice.modeling.lexicon import DEFAULT_LEXICON_PATH, load_lexicon
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import Annotation, Notice, Profile

DEFAULT_OUTPUT = Path("reports/generated/decision-reference-pilot")
POOL = ("train", "validation")


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_pool(split_dir: Path) -> tuple[list[Notice], list[Annotation], dict, dict]:
    notices, annotations, hashes = [], [], {}
    for split in POOL:
        for name in ("notices.jsonl", "annotations.jsonl"):
            hashes[f"{split}/{name}"] = _file_sha256(split_dir / split / name)
        notices += [
            Notice.model_validate(r) for r in read_jsonl(split_dir / split / "notices.jsonl")
        ]
        annotations += [
            Annotation.model_validate(r)
            for r in read_jsonl(split_dir / split / "annotations.jsonl")
        ]
    hashes["assignments.jsonl"] = _file_sha256(split_dir / "assignments.jsonl")
    assignments = {row["doc_id"]: row for row in read_jsonl(split_dir / "assignments.jsonl")}
    for notice in notices:
        if assignments.get(notice.doc_id, {}).get("split") not in POOL:
            raise ValueError(f"document {notice.doc_id} is not assigned to train or validation")
    return notices, annotations, assignments, hashes


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def _git() -> dict:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], encoding="utf-8").strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], encoding="utf-8").strip()
    return {"git_commit": commit, "git_dirty": bool(dirty)}


def sample(args: argparse.Namespace) -> None:
    notices, annotations, assignments, hashes = _load_pool(args.split_dir)
    constraints = [c for a in annotations for c in a.audience_constraints]
    profiles = generate_profiles(constraints, args.seed)
    pairs = build_pairs(notices, annotations, profiles)
    sources = {notice.doc_id: notice.source_type for notice in notices}
    rows = select_pilot(
        pairs,
        annotations,
        sources,
        quotas={"web": args.web, "email": args.email},
        profiles_per_event=args.profiles_per_event,
        seed=args.seed,
        max_events_per_doc=args.max_events_per_doc,
    )
    for row in rows:
        row |= {k: assignments[row["doc_id"]][k] for k in ("group_id", "split")}
    events = sorted({(row["doc_id"], row["event_id"]) for row in rows})
    repeats = sorted(Random(args.seed).sample(events, min(args.repeat_events, len(events))))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "sample.jsonl", rows)
    write_jsonl(args.output_dir / "profiles.jsonl", [p.model_dump(mode="json") for p in profiles])
    labels = Counter((row["source_type"], row["label"]) for row in rows)
    _write_json(
        args.output_dir / "sample.record.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "split_dir": args.split_dir.as_posix(),
            "inputs_sha256": hashes,
            "seed": args.seed,
            "quotas": {"web": args.web, "email": args.email},
            "profiles_per_event": args.profiles_per_event,
            "max_events_per_doc": args.max_events_per_doc,
            "audience_policy": "missing audiences stay UNCLEAR",
            "profile_count": len(profiles),
            "profile_set_sha256": json_sha256([p.model_dump(mode="json") for p in profiles]),
            "events": len(events),
            "pairs": len(rows),
            "hard_events": len({(r["doc_id"], r["event_id"]) for r in rows if r["hard_event"]}),
            "silver_labels_by_source": {
                f"{s}/{label}": n for (s, label), n in sorted(labels.items())
            },
            "repeat_events": [list(key) for key in repeats],
            "note": "Label-stratified sample; label mix is not a corpus estimate.",
            **_git(),
        },
    )
    print(f"{len(events)} events, {len(rows)} pairs: {args.output_dir / 'sample.jsonl'}")


def _jobs(args: argparse.Namespace, model: str) -> tuple[list[dict], dict]:
    record = json.loads((args.output_dir / "sample.record.json").read_text(encoding="utf-8"))
    notices, annotations, _, hashes = _load_pool(args.split_dir)
    if hashes != record["inputs_sha256"]:
        raise ValueError("split inputs changed since the sample was drawn")
    rows = read_jsonl(args.output_dir / "sample.jsonl")
    profiles = [Profile.model_validate(r) for r in read_jsonl(args.output_dir / "profiles.jsonl")]
    if json_sha256([p.model_dump(mode="json") for p in profiles]) != record["profile_set_sha256"]:
        raise ValueError("profiles.jsonl does not match the sample record")
    wanted = {(r["doc_id"], r["event_id"], r["profile_id"]): r["label"] for r in rows}
    docs = {doc for doc, _, _ in wanted}
    chosen = [
        p
        for p in build_pairs(notices, [a for a in annotations if a.doc_id in docs], profiles)
        if (p["doc_id"], p["event_id"], p["profile_id"]) in wanted
    ]
    if len(chosen) != len(wanted) or any(
        wanted[(p["doc_id"], p["event_id"], p["profile_id"])] != p["label"] for p in chosen
    ):
        raise ValueError("rebuilt pairs do not match the sample labels")
    lexicon, lexicon_sha = load_lexicon(DEFAULT_LEXICON_PATH)
    repeats = {tuple(key) for key in record["repeat_events"]}
    jobs = []
    for mode in args.modes:
        by_event = defaultdict(list)
        for item in build_inputs(chosen, notices, annotations, mode):
            by_event[(item.doc_id, item.event_id)].append(item)
        for (doc_id, event_id), items in sorted(by_event.items()):
            payload, questions = build_request(model, items, lexicon)
            for repeat in (0, 1) if (doc_id, event_id) in repeats else (0,):
                meta = {"mode": mode, "doc_id": doc_id, "event_id": event_id, "repeat": repeat}
                jobs.append(
                    {
                        "request_id": f"{mode}:{doc_id}:{event_id}:{repeat}",
                        "payload": payload,
                        "questions": questions,
                        "meta": meta,
                    }
                )
    return jobs[: args.limit] if args.limit else jobs, {"lexicon_sha256": lexicon_sha}


def run(args: argparse.Namespace) -> None:
    provider = PROVIDERS[args.provider]
    key = os.environ.get(provider.key_env)
    if not key:
        raise ValueError(f"set {provider.key_env} to run {provider.name}")
    jobs, extra = _jobs(args, provider.model)
    out = args.output_dir / provider.name
    started = datetime.now(UTC).isoformat()
    statuses = asyncio.run(
        run_requests(
            jobs,
            provider,
            key,
            out / "responses.jsonl",
            concurrency=args.concurrency,
            rate=args.rate,
        )
    )
    responses = read_jsonl(out / "responses.jsonl")
    _write_json(
        out / f"run.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.record.json",
        {
            "provider": provider.model_dump(),
            "returned_models": sorted({str(r["model"]) for r in responses if r.get("model")}),
            "instructions_version": INSTRUCTIONS_VERSION,
            "instructions_sha256": INSTRUCTIONS_SHA256,
            "modes": args.modes,
            "jobs": len(jobs),
            "sent_statuses": dict(statuses),
            "concurrency": args.concurrency,
            "rate_per_second": args.rate,
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "httpx": version("httpx"),
            **extra,
            **_git(),
        },
    )
    print(f"{provider.name}: {dict(statuses)} -> {out / 'responses.jsonl'}")


def score(args: argparse.Namespace) -> None:
    rows = read_jsonl(args.output_dir / "sample.jsonl")
    results, responses = {}, {}
    for name in args.providers:
        path = args.output_dir / name / "responses.jsonl"
        if path.exists():
            responses[name] = read_jsonl(path)
            results[name] = score_pilot(
                responses[name],
                rows,
                seed=args.seed,
                n_boot=args.n_boot,
                input_usd_per_mtok=PROVIDERS[name].input_usd_per_mtok,
            )
    if len(responses) == 2:
        first, second = responses.values()
        modes = {row["mode"] for row in first} & {row["mode"] for row in second}
        results["agreement"] = {mode: agreement(first, second, mode) for mode in sorted(modes)}
    _write_json(args.output_dir / "scores.json", results)
    print(f"scored {', '.join(responses) or 'nothing'}: {args.output_dir / 'scores.json'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("sample", "run", "score"):
        command = commands.add_parser(name)
        command.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
        command.add_argument("--seed", type=int, default=DEFAULT_SEED)
        if name in {"sample", "run"}:
            command.add_argument("--split-dir", type=Path, required=True)
    commands.choices["sample"].add_argument("--web", type=int, default=150)
    commands.choices["sample"].add_argument("--email", type=int, default=50)
    commands.choices["sample"].add_argument("--profiles-per-event", type=int, default=5)
    commands.choices["sample"].add_argument("--max-events-per-doc", type=int, default=3)
    commands.choices["sample"].add_argument("--repeat-events", type=int, default=20)
    runner = commands.choices["run"]
    runner.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    runner.add_argument("--modes", nargs="+", choices=["human", "none"], default=["none", "human"])
    runner.add_argument("--concurrency", type=int, default=8)
    runner.add_argument("--rate", type=float, default=20.0)
    runner.add_argument("--limit", type=int, help="send only the first N jobs (smoke test)")
    scorer = commands.choices["score"]
    scorer.add_argument("--providers", nargs="+", default=sorted(PROVIDERS))
    scorer.add_argument("--n-boot", type=int, default=1000)
    args = parser.parse_args(argv)
    try:
        {"sample": sample, "run": run, "score": score}[args.command](args)
    except ValueError as exc:
        sys.exit(f"decision_reference_pilot: {exc}")


if __name__ == "__main__":
    main()
