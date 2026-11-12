"""Run a private, reproducible tokenizer and preprocessing audit."""

import csv
import hashlib
import json
import platform
import random
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from huggingface_hub import snapshot_download
from sentencepiece import SentencePieceProcessor
from smartnotice.io import read_jsonl
from smartnotice.labeling.validation import validate_annotation
from smartnotice.preprocessing.links import find_link_occurrences
from smartnotice.preprocessing.split import DEFAULT_SEED, split_documents
from smartnotice.preprocessing.text_audit import TextFinding, review_stratum, scan_prepared_text
from smartnotice.preprocessing.token_audit import (
    TokenWindow,
    boundary_lengths,
    co_visible,
    covered_characters,
    head_range,
    input_length,
    interval_retention,
    make_windows,
)
from smartnotice.schemas import (
    Annotation,
    AuditReviewFinding,
    LMAuditContextRecord,
    LMAuditEvidenceRecord,
    LMAuditReviewItem,
    LMAuditURLRecord,
    LMAuditWindowRecord,
    Notice,
    PreprocessingAnomaly,
)
from tokenizers import Tokenizer

BAMI_MODEL = "Qualcomm-AI-Research/BamiBERT"
BAMI_REVISION = "57bc1340debbe4e348ec549047a763caebe4a977"
VIT5_MODEL = "VietAI/vit5-base"
VIT5_REVISION = "2209a38d735ede63e88f5aa52bcdc11a05a37b85"
TEMPLATES = {
    "text_only_v1": {"bami": "", "vit5": ""},
    "proposed_event_v1": {
        "bami": "Trích xuất sự kiện học vụ: ",
        "vit5": "trích xuất sự kiện học vụ: ",
    },
}
POLICIES = [
    "keep_if_fits",
    "simulated_head_truncation",
    "token_windows_overlap_0",
    "token_windows_overlap_64",
    "token_windows_overlap_128",
]


def _sha256(path: Path) -> str:
    """Hash one input file without loading a large corpus into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_hash(text: str) -> str:
    """Hash prepared UTF-8 text for exact snapshot provenance."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for row in rows:
            if hasattr(row, "model_dump"):
                row = row.model_dump(mode="json")
            target.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    if columns is None:
        columns = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _percentile(values: list[int], q: float) -> int | None:
    """Return the nearest-rank percentile as an integer token count."""
    if not values:
        return None
    values = sorted(values)
    return values[max(0, min(len(values) - 1, int((len(values) - 1) * q + 0.5)))]


def _download_tokenizer(model_id: str, revision: str, cache_dir: Path) -> tuple[Tokenizer, Path]:
    """Download only pinned tokenizer/config files and load the fast tokenizer."""
    local = snapshot_download(
        repo_id=model_id,
        revision=revision,
        cache_dir=str(cache_dir),
        allow_patterns=[
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "added_tokens.json",
            "spiece.model",
            "vocab.json",
            "merges.txt",
        ],
        local_files_only=False,
    )
    directory = Path(local)
    tokenizer_path = directory / "tokenizer.json"
    if not tokenizer_path.is_file():
        raise ValueError(f"Pinned model {model_id} has no tokenizer.json")
    return Tokenizer.from_file(str(tokenizer_path)), directory


def _sample_review(notices: list[Notice], flagged: set[str], seed: int) -> dict[str, list[Notice]]:
    """Select a reproducible, roughly balanced unflagged sample by source/stratum."""
    rng = random.Random(seed)
    selected: dict[str, list[Notice]] = {"email": [], "web": []}
    targets = {"email": 30, "web": 20}
    pools: dict[str, dict[str, list[Notice]]] = {
        "email": defaultdict(list),
        "web": defaultdict(list),
    }
    for notice in notices:
        if notice.doc_id not in flagged:
            stratum = "/".join(review_stratum(notice)[1:4])
            pools[notice.source_type][stratum].append(notice)
    for source_type, count in targets.items():
        for pool in pools[source_type].values():
            rng.shuffle(pool)
        strata = sorted(pools[source_type])
        while len(selected[source_type]) < count and strata:
            remaining = []
            for stratum in strata:
                if pools[source_type][stratum] and len(selected[source_type]) < count:
                    selected[source_type].append(pools[source_type][stratum].pop())
                if pools[source_type][stratum]:
                    remaining.append(stratum)
            strata = remaining
    return selected


def _policy_windows(
    tokenizer: Tokenizer, text: str, prefix: str, limit: int, policy: str, full_tokens: int
) -> list[TokenWindow]:
    """Build model-visible character ranges for one explicit long-text policy."""
    if policy == "keep_if_fits":
        return [TokenWindow(0, 0, 0, 0, len(text), full_tokens)] if full_tokens <= limit else []
    if policy == "simulated_head_truncation":
        _, start, end, _ = head_range(tokenizer, text, prefix, limit)
        return [TokenWindow(0, 0, 0, start, end, min(full_tokens, limit))]
    overlap = int(policy.rsplit("_", 1)[1])
    return make_windows(tokenizer, text, prefix, limit, overlap)


def _finding_status(start: int, end: int, windows: list[TokenWindow]) -> str:
    """Classify a source range as whole in one window, partial, or absent."""
    if any(window.char_start <= start and end <= window.char_end for window in windows):
        return "retained"
    if any(max(start, window.char_start) < min(end, window.char_end) for window in windows):
        return "partial"
    return "lost"


def _preprocessing_replay_summary(current_email: list[Notice], replayed: list[Notice]) -> dict:
    """Compare replay provenance and prepared fields without exposing source text."""
    current_by_id = {notice.doc_id: notice for notice in current_email}
    replay_by_id = {notice.doc_id: notice for notice in replayed}
    common = set(current_by_id) & set(replay_by_id)
    attachment_mismatches = sorted(
        doc_id
        for doc_id in common
        if replay_by_id[doc_id].attachments != current_by_id[doc_id].attachments
    )
    return {
        "status": "completed_with_missing_raw_sources"
        if len(replayed) < len(current_email)
        else "completed",
        "available_raw_email_records": len(replayed),
        "matched_doc_ids": len(common),
        "raw_hash_matches": sum(
            replay_by_id[doc_id].raw_sha256 == current_by_id[doc_id].raw_sha256 for doc_id in common
        ),
        "prepared_text_hash_matches": sum(
            _text_hash(replay_by_id[doc_id].text) == _text_hash(current_by_id[doc_id].text)
            for doc_id in common
        ),
        "sentence_offset_matches": sum(
            [sentence.model_dump(mode="json") for sentence in replay_by_id[doc_id].sentences]
            == [sentence.model_dump(mode="json") for sentence in current_by_id[doc_id].sentences]
            for doc_id in common
        ),
        "metadata_attachments_matches": sum(
            replay_by_id[doc_id].attachments == current_by_id[doc_id].attachments
            for doc_id in common
        ),
        "replay_attachment_entries": sum(
            len(replay_by_id[doc_id].attachments) for doc_id in common
        ),
        "snapshot_empty_attachment_doc_ids": sorted(
            doc_id
            for doc_id in common
            if not current_by_id[doc_id].attachments and replay_by_id[doc_id].attachments
        ),
        "attachment_mismatch_doc_ids": attachment_mismatches,
        "text_mismatch_doc_ids": sorted(
            doc_id
            for doc_id in common
            if _text_hash(replay_by_id[doc_id].text) != _text_hash(current_by_id[doc_id].text)
        ),
        "raw_hash_mismatch_doc_ids": sorted(
            doc_id
            for doc_id in common
            if replay_by_id[doc_id].raw_sha256 != current_by_id[doc_id].raw_sha256
        ),
        "current_email_records": len(current_email),
        "missing_raw_doc_ids": sorted(set(current_by_id) - set(replay_by_id)),
        "orphan_replay_doc_ids": sorted(set(replay_by_id) - set(current_by_id)),
        "web_raw_status": "not_available_in_selected_drive_raw_folder",
    }


def _record_evidence_unit(
    counts: dict[tuple, Counter],
    spec: dict,
    template_id: str,
    policy: str,
    notice: Notice,
    split: str,
    windows: list[TokenWindow],
    unit: str,
    label: str,
    ranges: list[tuple[int, int]],
    relation: bool = False,
) -> None:
    """Add one validated source unit to its model/policy evidence group."""
    group = (
        spec["key"],
        spec["model_id"],
        spec["revision"],
        template_id,
        policy,
        notice.source_type,
        split,
        notice.synthetic,
        "human_annotation_valid",
        unit,
        label,
    )
    item = counts[group]
    item["units_total"] += 1
    if all(_finding_status(start, end, windows) == "retained" for start, end in ranges):
        item["fully_visible"] += 1
    elif any(_finding_status(start, end, windows) != "lost" for start, end in ranges):
        item["partially_visible"] += 1
    else:
        item["not_visible"] += 1
    if relation and not co_visible(ranges, windows):
        item["not_co_visible"] += 1
    elif relation:
        item["co_visible"] += 1


def _aggregate_evidence(
    annotations: dict[str, Annotation],
    notice_by_id: dict[str, Notice],
    split_by_id: dict[str, str],
    windows_by_key: dict[tuple[str, str, str, str], list[TokenWindow]],
    model_specs: list[dict],
    template_ids: list[str],
) -> list[dict]:
    """Measure valid annotation unit coverage and co-visibility by policy."""
    counts: dict[tuple, Counter] = defaultdict(Counter)
    annotated_documents: Counter = Counter()
    for doc_id, annotation in annotations.items():
        notice = notice_by_id[doc_id]
        split = split_by_id[doc_id]
        spans = {span.span_id: span for span in annotation.spans}
        sentences = {sentence.sentence_id: sentence for sentence in notice.sentences}
        annotated_documents[(notice.source_type, split, notice.synthetic)] += 1
        for spec in model_specs:
            for template_id in template_ids:
                for policy in POLICIES:
                    key = (doc_id, spec["key"], template_id, policy)
                    windows = windows_by_key[key]

                    for span in annotation.spans:
                        _record_evidence_unit(
                            counts,
                            spec,
                            template_id,
                            policy,
                            notice,
                            split,
                            windows,
                            "span",
                            span.label,
                            [(span.start, span.end)],
                        )
                    deadline_ids = {
                        argument.span_id
                        for event in annotation.events
                        for argument in event.arguments
                        if argument.role == "DEADLINE"
                    }
                    for span_id in deadline_ids:
                        span = spans[span_id]
                        _record_evidence_unit(
                            counts,
                            spec,
                            template_id,
                            policy,
                            notice,
                            split,
                            windows,
                            "deadline",
                            "TIME_DEADLINE",
                            [(span.start, span.end)],
                        )
                    for event in annotation.events:
                        action = spans[event.action_span_id]
                        for argument in event.arguments:
                            target = spans[argument.span_id]
                            _record_evidence_unit(
                                counts,
                                spec,
                                template_id,
                                policy,
                                notice,
                                split,
                                windows,
                                "action_argument_relation",
                                f"{target.label}_{argument.role or 'NONE'}",
                                [(action.start, action.end), (target.start, target.end)],
                                relation=True,
                            )
                        event_ranges = [(action.start, action.end)]
                        event_ranges.extend(
                            (spans[arg.span_id].start, spans[arg.span_id].end)
                            for arg in event.arguments
                        )
                        event_ranges.extend(
                            (sentences[sid].start, sentences[sid].end)
                            for sid in event.evidence_sentence_ids
                        )
                        _record_evidence_unit(
                            counts,
                            spec,
                            template_id,
                            policy,
                            notice,
                            split,
                            windows,
                            "event",
                            "complete_action_arguments_evidence",
                            event_ranges,
                            relation=True,
                        )
    rows = []
    for spec in model_specs:
        for template_id in template_ids:
            for policy in POLICIES:
                for source in ("email", "web"):
                    for split in (
                        "train",
                        "validation",
                        "test",
                        "domain_test",
                        "excluded",
                        "unassigned",
                    ):
                        for synthetic in (False, True):
                            groups = [
                                (key, value)
                                for key, value in counts.items()
                                if key[:5]
                                == (
                                    spec["key"],
                                    spec["model_id"],
                                    spec["revision"],
                                    template_id,
                                    policy,
                                )
                                and key[5:8] == (source, split, synthetic)
                            ]
                            if groups:
                                for key, value in groups:
                                    rows.append(
                                        LMAuditEvidenceRecord(
                                            run_id="",
                                            model_key=key[0],
                                            model_id=key[1],
                                            model_revision=key[2],
                                            template_id=key[3],
                                            policy=key[4],
                                            source_type=key[5],
                                            split=key[6],
                                            synthetic=key[7],
                                            annotation_source=key[8],
                                            unit=key[9],
                                            label=key[10],
                                            documents_with_annotations=annotated_documents[
                                                (source, split, synthetic)
                                            ],
                                            units_total=value["units_total"],
                                            fully_visible=value["fully_visible"],
                                            partially_visible=value["partially_visible"],
                                            not_visible=value["not_visible"],
                                            not_co_visible=value["not_co_visible"],
                                            status="measured",
                                        ).model_dump(mode="json")
                                    )
                            else:
                                rows.append(
                                    LMAuditEvidenceRecord(
                                        run_id="",
                                        model_key=spec["key"],
                                        model_id=spec["model_id"],
                                        model_revision=spec["revision"],
                                        template_id=template_id,
                                        policy=policy,
                                        source_type=source,
                                        split=split,
                                        synthetic=synthetic,
                                        annotation_source="human_annotation_valid",
                                        unit="all",
                                        label="all",
                                        documents_with_annotations=annotated_documents[
                                            (source, split, synthetic)
                                        ],
                                        units_total=0,
                                        fully_visible=0,
                                        partially_visible=0,
                                        not_visible=0,
                                        not_co_visible=0,
                                        status="not_evaluable",
                                    ).model_dump(mode="json")
                                )
    return rows


def _render_figures(output: Path, token_rows: list[dict], summary_rows: list[dict]) -> None:
    """Render aggregate-only figures with no source text or private identifiers."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = output / "figures"
    figures.mkdir()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for axis, (key, title) in zip(
        axes, (("bami", "BamiBERT · 2.048"), ("vit5", "ViT5 · 1.024")), strict=True
    ):
        model_rows = [
            row["input_tokens"]
            for row in token_rows
            if row["model_key"] == key
            and row["template_id"] == "text_only_v1"
            and not row["synthetic"]
        ]
        max_tokens = max(model_rows, default=1)
        bins = [max_tokens * index / 30 for index in range(31)]
        for source, color in (("email", "#386cb0"), ("web", "#1b9e77")):
            values = [
                row["input_tokens"]
                for row in token_rows
                if row["model_key"] == key
                and row["template_id"] == "text_only_v1"
                and row["source_type"] == source
                and not row["synthetic"]
            ]
            axis.hist(values, bins=bins, color=color, alpha=0.65, label=source)
        axis.axvline(
            2048 if key == "bami" else 1024, color="#d95f02", linestyle="--", label="context"
        )
        axis.set_title(title)
        axis.set_xlabel("Token đầu vào (gồm special tokens)")
        axis.set_ylabel("Số tài liệu")
        axis.legend(frameon=False)
    fig.savefig(figures / "token_distribution.png", dpi=160)
    plt.close(fig)
    rows = [
        r
        for r in summary_rows
        if r["template_id"] == "text_only_v1"
        and r["source_type"] == "email"
        and r["split"] in {"train", "validation"}
        and not r["synthetic"]
    ]
    policies = [
        "simulated_head_truncation",
        "token_windows_overlap_0",
        "token_windows_overlap_64",
        "token_windows_overlap_128",
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for axis, key, title in zip(axes, ("bami", "vit5"), ("BamiBERT", "ViT5"), strict=True):
        selected = [r for r in rows if r["model_key"] == key]
        totals = defaultdict(int)
        denoms = defaultdict(int)
        for row in selected:
            totals[row["policy"]] += row["partial_documents"]
            denoms[row["policy"]] += row["documents"]
        ratios = [100 * totals[p] / denoms[p] if denoms[p] else 0 for p in policies]
        axis.bar(range(len(policies)), ratios, color="#1b9e77")
        axis.set_xticks(range(len(policies)), ["head", "win 0", "win 64", "win 128"])
        axis.set_ylim(0, max(5, max(ratios, default=0) * 1.2))
        axis.set_title(title + " · email train/validation")
        axis.set_ylabel("Tài liệu có cắt (%)")
    fig.savefig(figures / "policy_partial_email.png", dpi=160)
    plt.close(fig)


def run_lm_audit(
    notice_paths: list[Path],
    *,
    annotations_path: Path | None,
    reference_splits_path: Path | None,
    output_dir: Path,
    run_id: str,
    seed: int = DEFAULT_SEED,
    similarity: float = 0.9,
    cache_dir: Path = Path("data/interim/lm_audit_snapshot/tokenizer_cache"),
    email_manifest_path: Path | None = None,
    web_manifest_path: Path | None = None,
    historical_notices_path: Path | None = None,
    raw_replay_notices_path: Path | None = None,
    raw_manifest_path: Path | None = None,
    bami_context: int = 2048,
    vit5_context: int = 1024,
    bami_model: str = BAMI_MODEL,
    bami_revision: str = BAMI_REVISION,
    vit5_model: str = VIT5_MODEL,
    vit5_revision: str = VIT5_REVISION,
    template_ids: list[str] | None = None,
) -> dict:
    """Measure two pinned model tokenizers on a selected, private notice snapshot.

    Existing outputs are never replaced. The returned summary contains only
    counts and paths, not raw notice text, URLs, consent references, or names.
    """
    if output_dir.exists():
        raise ValueError("Audit output directory already exists; choose a new run ID")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}-", dir=output_dir.parent))
    try:
        input_paths = [*notice_paths]
        if annotations_path:
            input_paths.append(annotations_path)
        if reference_splits_path:
            input_paths.append(reference_splits_path)
        if email_manifest_path:
            input_paths.append(email_manifest_path)
        if web_manifest_path:
            input_paths.append(web_manifest_path)
        if historical_notices_path:
            input_paths.append(historical_notices_path)
        if raw_replay_notices_path:
            input_paths.append(raw_replay_notices_path)
        if raw_manifest_path:
            input_paths.append(raw_manifest_path)
        selected_templates = template_ids or list(TEMPLATES)
        if not selected_templates or any(
            template not in TEMPLATES for template in selected_templates
        ):
            raise ValueError("Choose one or more supported audit templates")
        notices = [Notice.model_validate(row) for path in notice_paths for row in read_jsonl(path)]
        if not notices:
            raise ValueError("No notices were loaded")
        ids = [notice.doc_id for notice in notices]
        if len(ids) != len(set(ids)):
            raise ValueError("Input snapshot contains duplicate document IDs")
        notice_by_id = {notice.doc_id: notice for notice in notices}
        split_rows = split_documents(notices, seed, similarity)
        split_path = temporary / "split_assignments.jsonl"
        _write_jsonl(split_path, split_rows)
        split_by_id = {row["doc_id"]: row["split"] for row in split_rows}
        baseline_split_rows = read_jsonl(reference_splits_path) if reference_splits_path else []
        baseline_map = {
            row["doc_id"]: row.get("split", "unassigned") for row in baseline_split_rows
        }
        historical_match = {
            "records": 0,
            "matched_ids": 0,
            "text_hash_matches": 0,
            "raw_hash_matches": 0,
            "group_id_matches": 0,
        }
        if historical_notices_path:
            historical = {
                row["doc_id"]: Notice.model_validate(row)
                for row in read_jsonl(historical_notices_path)
            }
            current_emails = {n.doc_id: n for n in notices if n.source_type == "email"}
            historical_match["records"] = len(historical)
            historical_match["matched_ids"] = sum(doc_id in historical for doc_id in current_emails)
            historical_match["text_hash_matches"] = sum(
                doc_id in historical
                and _text_hash(notice.text) == _text_hash(historical[doc_id].text)
                for doc_id, notice in current_emails.items()
            )
            historical_match["raw_hash_matches"] = sum(
                doc_id in historical and notice.raw_sha256 == historical[doc_id].raw_sha256
                for doc_id, notice in current_emails.items()
            )
            historical_match["group_id_matches"] = sum(
                doc_id in historical and notice.group_id == historical[doc_id].group_id
                for doc_id, notice in current_emails.items()
            )
        replay_summary = {
            "status": "not_run",
            "available_raw_email_records": 0,
            "matched_doc_ids": 0,
            "raw_hash_matches": 0,
            "prepared_text_hash_matches": 0,
            "sentence_offset_matches": 0,
            "metadata_attachments_matches": 0,
            "replay_attachment_entries": 0,
            "snapshot_empty_attachment_doc_ids": [],
            "attachment_mismatch_doc_ids": [],
            "text_mismatch_doc_ids": [],
            "raw_hash_mismatch_doc_ids": [],
            "current_email_records": sum(n.source_type == "email" for n in notices),
            "web_raw_status": "not_available_in_selected_drive_raw_folder",
        }
        if raw_replay_notices_path:
            replayed = [Notice.model_validate(row) for row in read_jsonl(raw_replay_notices_path)]
            replay_summary = _preprocessing_replay_summary(
                [notice for notice in notices if notice.source_type == "email"], replayed
            )
        _json(temporary / "preprocessing_replay.json", replay_summary)
        model_specs = [
            {
                "key": "bami",
                "model_id": bami_model,
                "revision": bami_revision,
                "limit": bami_context,
            },
            {
                "key": "vit5",
                "model_id": vit5_model,
                "revision": vit5_revision,
                "limit": vit5_context,
            },
        ]
        tokenizer_data = {}
        model_checks = []
        cache_dir.mkdir(parents=True, exist_ok=True)
        for spec in model_specs:
            tokenizer, directory = _download_tokenizer(
                spec["model_id"], spec["revision"], cache_dir
            )
            spec["tokenizer"] = tokenizer
            spec["directory"] = directory
            spec["files"] = {
                path.name: _sha256(path) for path in sorted(directory.iterdir()) if path.is_file()
            }
            spec["special_single"] = len(tokenizer.encode("", add_special_tokens=True).ids)
            spec["special_pair"] = len(tokenizer.encode("", "", add_special_tokens=True).ids)
            spec["template_sha"] = {
                name: _text_hash(TEMPLATES[name][spec["key"]]) for name in TEMPLATES
            }
            spec["boundaries"] = boundary_lengths(
                tokenizer, "Nộp", TEMPLATES["text_only_v1"][spec["key"]], spec["limit"]
            )
            sample = "Nộp hồ sơ tại https://example.edu.vn/học-vụ?id=1; hạn ngày 30/11/2026 🧭"
            pair_length = input_length(tokenizer, sample, pair="Sinh viên khóa 2024")
            check = {
                "model_key": spec["key"],
                "model_id": spec["model_id"],
                "revision": spec["revision"],
                "context_limit": spec["limit"],
                "single_special_tokens": spec["special_single"],
                "pair_special_tokens": spec["special_pair"],
                "boundary_probe": spec["boundaries"],
                "synthetic_pair_input_tokens": pair_length,
                "tokenizer_file_sha256": spec["files"],
                "input_variants": {
                    "nli_profile_pair": {
                        "status": "not_evaluable",
                        "reason": "No canonical event/profile pair inputs exist in the repository "
                        "snapshot.",
                    },
                    "vit5_decoder_target": {
                        "status": "not_evaluable",
                        "reason": (
                            "No canonical ViT5 target serialization or training caller exists."
                        ),
                    },
                },
                "training_or_inference_caller": "not_found_outside_this_audit_module",
                "model_smoke": {
                    "status": "not_run",
                    "reason": "Tokenizer-only audit; model weights and torch were not fetched.",
                },
            }
            if spec["key"] == "vit5" and (directory / "spiece.model").exists():
                sp = SentencePieceProcessor(model_file=str(directory / "spiece.model"))
                parity_samples = [
                    sample,
                    "NFC tiếng Việt: trường/khoa, ngày 03/12/2026",
                    "https://example.edu/a%2Fb?x=1",
                    "e\u0302\u0301 và emoji 📚",
                ]
                encoded_pairs = [
                    (
                        sp.encode(value, out_type=int),
                        tokenizer.encode(value, add_special_tokens=False).ids,
                    )
                    for value in parity_samples
                ]
                check["sentencepiece_parity"] = {
                    "samples": len(parity_samples),
                    "sequence_mismatches": sum(left != right for left, right in encoded_pairs),
                    "token_count_mismatches": sum(
                        len(left) != len(right) for left, right in encoded_pairs
                    ),
                }
            else:
                check["sentencepiece_parity"] = {"status": "not_applicable"}
            model_checks.append(check)
            tokenizer_data[spec["key"]] = tokenizer
        _json(
            temporary / "model_checks.json",
            {
                "official_sources": {
                    "bami": "https://huggingface.co/Qualcomm-AI-Research/BamiBERT",
                    "vit5": "https://github.com/vietai/ViT5",
                },
                "vit5_choice": (
                    "VietAI/vit5-base is a provisional base-checkpoint assumption; "
                    "no repository training config selects a ViT5 checkpoint."
                ),
                "replay_attachment_entries": replay_summary["replay_attachment_entries"],
                "snapshot_empty_attachment_documents": len(
                    replay_summary["snapshot_empty_attachment_doc_ids"]
                ),
                "attachment_mismatch_documents": len(replay_summary["attachment_mismatch_doc_ids"]),
                "templates": {
                    name: {
                        "bami": TEMPLATES[name]["bami"],
                        "vit5": TEMPLATES[name]["vit5"],
                        "status": "baseline"
                        if name == "text_only_v1"
                        else "proposed_not_training_config",
                    }
                    for name in selected_templates
                },
                "models": model_checks,
            },
        )
        valid_annotations: dict[str, Annotation] = {}
        annotation_failures = 0
        if annotations_path:
            for row in read_jsonl(annotations_path):
                try:
                    annotation = Annotation.model_validate(row)
                    notice = notice_by_id[annotation.doc_id]
                    validate_annotation(annotation, notice)
                except (ValueError, KeyError, TypeError):
                    annotation_failures += 1
                    continue
                valid_annotations[annotation.doc_id] = annotation
        source_counts = Counter(n.source_type for n in notices)
        synthetic_counts = Counter((n.source_type, n.synthetic) for n in notices)
        _json(
            temporary / "snapshot_validation.json",
            {
                "records": len(notices),
                "unique_doc_ids": len(ids),
                "source_type_counts": dict(source_counts),
                "synthetic_counts": {
                    f"{source}:{'synthetic' if synthetic else 'research'}": count
                    for (source, synthetic), count in synthetic_counts.items()
                },
                "parser_warning_documents": sum(bool(n.parser_warnings) for n in notices),
                "privacy_review_required_documents": sum(
                    n.privacy_review_required for n in notices
                ),
                "valid_human_annotation_records": len(valid_annotations),
                "invalid_annotation_records": annotation_failures,
                "annotation_sources": {
                    "email": sum(
                        notice_by_id[doc_id].source_type == "email" for doc_id in valid_annotations
                    ),
                    "web": sum(
                        notice_by_id[doc_id].source_type == "web" for doc_id in valid_annotations
                    ),
                },
                "baseline_split_records": len(baseline_map),
                "baseline_split_matches": sum(doc_id in baseline_map for doc_id in ids),
                "historical_preprocess_comparison": historical_match,
                "preprocessing_replay": {
                    key: value
                    for key, value in replay_summary.items()
                    if not key.endswith("doc_ids")
                },
                "audit_split_counts": dict(Counter(row["split"] for row in split_rows)),
                "domain_test_documents": sum(row["split"] == "domain_test" for row in split_rows),
            },
        )
        # Verify available prepared-text manifests without serializing source refs.
        manifest_checks = {}
        for label, path in (
            ("email_prediction_manifest", email_manifest_path),
            ("web_preprocess_manifest", web_manifest_path),
        ):
            if not path:
                continue
            rows = read_jsonl(path)
            current = {n.doc_id: _text_hash(n.text) for n in notices}
            mismatches = 0
            missing = 0
            field = "text_sha256" if label.startswith("email") else "prepared_text_sha256"
            for row in rows:
                if row.get("doc_id") not in current:
                    missing += 1
                elif row.get(field) != current[row["doc_id"]]:
                    mismatches += 1
            manifest_checks[label] = {
                "rows": len(rows),
                "missing_notice": missing,
                "text_hash_mismatch": mismatches,
                "hash_field": field,
            }
        _json(temporary / "provenance_reconciliation.json", manifest_checks)

        token_rows = []
        context_models = []
        windows_by_key: dict[tuple[str, str, str, str], list[TokenWindow]] = {}
        url_rows = []
        window_rows = []
        policy_summary: dict[tuple, Counter] = defaultdict(Counter)
        doc_policy_data: dict[tuple, dict] = {}
        url_counts = Counter()
        for notice in notices:
            text_sha = _text_hash(notice.text)
            split = split_by_id[notice.doc_id]
            urls = find_link_occurrences(notice.text)
            unique_urls = {url.canonical_key for url in urls}
            url_counts[(notice.source_type, split, "occurrences")] += len(urls)
            url_counts[(notice.source_type, split, "unique_document_urls")] += len(unique_urls)
            for spec in model_specs:
                tokenizer = spec["tokenizer"]
                for template_id in selected_templates:
                    prefix = TEMPLATES[template_id][spec["key"]]
                    template_hash = spec["template_sha"][template_id]
                    body_tokens = len(tokenizer.encode(notice.text, add_special_tokens=False).ids)
                    full_tokens = input_length(tokenizer, prefix + notice.text)
                    special_count = len(
                        tokenizer.encode(prefix + notice.text, add_special_tokens=True).ids
                    ) - len(tokenizer.encode(prefix + notice.text, add_special_tokens=False).ids)
                    head_tokens, _, head_end, body_kept = head_range(
                        tokenizer, notice.text, prefix, spec["limit"]
                    )
                    token_record = LMAuditContextRecord(
                        run_id=run_id,
                        doc_id=notice.doc_id,
                        text_sha256=text_sha,
                        source_type=notice.source_type,
                        split=split,
                        synthetic=notice.synthetic,
                        model_key=spec["key"],
                        model_id=spec["model_id"],
                        model_revision=spec["revision"],
                        template_id=template_id,
                        template_sha256=template_hash,
                        context_limit=spec["limit"],
                        text_characters=len(notice.text),
                        text_tokens=body_tokens,
                        input_tokens=full_tokens,
                        prefix_tokens=len(tokenizer.encode(prefix, add_special_tokens=False).ids),
                        special_tokens=special_count,
                        overflow=full_tokens > spec["limit"],
                        head_input_tokens=head_tokens,
                        source_tokens_retained_head=body_kept,
                        source_tokens_lost_head=max(0, body_tokens - body_kept),
                        status="measured",
                    ).model_dump(mode="json")
                    token_rows.append(token_record)
                    context_models.append(token_record)
                    for policy in POLICIES:
                        policy_windows = _policy_windows(
                            tokenizer, notice.text, prefix, spec["limit"], policy, full_tokens
                        )
                        key = (notice.doc_id, spec["key"], template_id, policy)
                        windows_by_key[key] = policy_windows
                        key_summary = (
                            spec["key"],
                            spec["model_id"],
                            spec["revision"],
                            template_id,
                            policy,
                            notice.source_type,
                            split,
                            notice.synthetic,
                        )
                        agg = policy_summary[key_summary]
                        agg["documents"] += 1
                        agg["overflow_documents"] += full_tokens > spec["limit"]
                        agg["windows"] += len(policy_windows)
                        agg["window_tokens"] += sum(
                            window.input_tokens for window in policy_windows
                        )
                        agg["source_characters_total"] += len(notice.text)
                        agg["source_characters_visible"] += covered_characters(
                            0,
                            len(notice.text),
                            [(window.char_start, window.char_end) for window in policy_windows],
                        )
                        if policy == "keep_if_fits" and full_tokens > spec["limit"]:
                            status = "unhandled_overflow"
                        elif not policy_windows:
                            status = "dropped"
                        elif not notice.text:
                            status = "retained"
                        else:
                            status = interval_retention(
                                0,
                                len(notice.text),
                                [(window.char_start, window.char_end) for window in policy_windows],
                            )
                        agg[f"{status}_documents"] += 1
                        agg["source_tokens_lost_head"] += (
                            token_record["source_tokens_lost_head"]
                            if policy == "simulated_head_truncation"
                            else 0
                        )
                        agg["overflow_tokens"] += max(0, full_tokens - spec["limit"])
                        policy_input = sum(window.input_tokens for window in policy_windows)
                        agg["input_tokens_total"] += policy_input
                        agg["max_windows"] = max(agg["max_windows"], len(policy_windows))
                        doc_policy_data[key] = {
                            "windows": policy_windows,
                            "status": status,
                            "input_tokens": policy_input,
                            "full_tokens": full_tokens,
                        }
                        window_output = []
                        for window in policy_windows:
                            window_output.append(
                                LMAuditWindowRecord(
                                    run_id=run_id,
                                    doc_id=notice.doc_id,
                                    model_key=spec["key"],
                                    model_id=spec["model_id"],
                                    model_revision=spec["revision"],
                                    template_id=template_id,
                                    policy=policy,
                                    window_id=window.window_id,
                                    input_tokens=window.input_tokens,
                                    body_token_start=window.token_start,
                                    body_token_end=window.token_end,
                                    source_char_ranges=[(window.char_start, window.char_end)],
                                ).model_dump(mode="json")
                            )
                        # Write window rows later, avoiding per-document file opens.
                        window_rows.extend(window_output)
                        for index, occurrence in enumerate(urls):
                            retained = _finding_status(
                                occurrence.start, occurrence.end, policy_windows
                            )
                            occurrence_id = hashlib.sha256(
                                f"{notice.doc_id}:{index}:{occurrence.start}:{occurrence.end}".encode()
                            ).hexdigest()[:24]
                            document_url_id = hashlib.sha256(
                                f"{notice.doc_id}:{occurrence.canonical_key}".encode()
                            ).hexdigest()[:24]
                            url_rows.append(
                                LMAuditURLRecord(
                                    run_id=run_id,
                                    occurrence_id=occurrence_id,
                                    document_url_id=document_url_id,
                                    url_sha256=hashlib.sha256(
                                        occurrence.canonical_key.encode()
                                    ).hexdigest(),
                                    doc_id=notice.doc_id,
                                    source_type=notice.source_type,
                                    split=split,
                                    synthetic=notice.synthetic,
                                    start=occurrence.start,
                                    end=occurrence.end,
                                    model_key=spec["key"],
                                    model_id=spec["model_id"],
                                    model_revision=spec["revision"],
                                    template_id=template_id,
                                    policy=policy,
                                    retention=retained,
                                ).model_dump(mode="json")
                            )
        _write_csv(temporary / "token_lengths.csv", token_rows)
        _write_jsonl(temporary / "windows.jsonl", window_rows)
        _write_jsonl(temporary / "url_retention.jsonl", url_rows)

        summary_rows = []
        for key, counts in sorted(policy_summary.items()):
            model_key, model_id, revision, template_id, policy, source, split, synthetic = key
            base = [
                r
                for r in token_rows
                if (r["model_key"], r["template_id"], r["source_type"], r["split"])
                == (model_key, template_id, source, split)
                and r["synthetic"] == synthetic
            ]
            tokens = [r["input_tokens"] for r in base]
            summary_rows.append(
                {
                    "model_key": model_key,
                    "model_id": model_id,
                    "model_revision": revision,
                    "template_id": template_id,
                    "policy": policy,
                    "source_type": source,
                    "split": split,
                    "synthetic": synthetic,
                    "documents": counts["documents"],
                    "measured_documents": counts["documents"],
                    "overflow_documents": counts["overflow_documents"],
                    "retained_documents": counts["retained_documents"],
                    "partial_documents": counts["partial_documents"],
                    "dropped_documents": counts["dropped_documents"],
                    "unhandled_overflow_documents": counts["unhandled_overflow_documents"],
                    "source_tokens_lost_head": counts["source_tokens_lost_head"],
                    "overflow_tokens": counts["overflow_tokens"],
                    "window_count": counts["windows"],
                    "mean_windows": round(counts["windows"] / max(1, counts["documents"]), 3),
                    "input_tokens_total": counts["input_tokens_total"],
                    "mean_full_input_tokens": round(sum(tokens) / max(1, len(tokens)), 2),
                    "source_characters_total": counts["source_characters_total"],
                    "source_characters_visible": counts["source_characters_visible"],
                    "source_char_coverage": round(
                        counts["source_characters_visible"]
                        / max(1, counts["source_characters_total"]),
                        6,
                    ),
                    "min_input_tokens": min(tokens) if tokens else None,
                    "p50_input_tokens": _percentile(tokens, 0.50),
                    "p75_input_tokens": _percentile(tokens, 0.75),
                    "p90_input_tokens": _percentile(tokens, 0.90),
                    "p95_input_tokens": _percentile(tokens, 0.95),
                    "p99_input_tokens": _percentile(tokens, 0.99),
                    "max_input_tokens": max(tokens) if tokens else None,
                }
            )
        _write_csv(temporary / "context_summary.csv", summary_rows)

        # Build evidence rows for every policy from only offset-validated human annotations.
        evidence_rows = _aggregate_evidence(
            valid_annotations,
            notice_by_id,
            split_by_id,
            windows_by_key,
            model_specs,
            selected_templates,
        )
        for row in evidence_rows:
            row["run_id"] = run_id
        _write_csv(temporary / "evidence_coverage.csv", evidence_rows)

        anomaly_rows = []
        findings_by_id: dict[str, list] = defaultdict(list)
        for notice in notices:
            for finding in scan_prepared_text(notice.text, notice.parser_warnings):
                row = PreprocessingAnomaly(
                    doc_id=notice.doc_id,
                    text_sha256=_text_hash(notice.text),
                    source_type=notice.source_type,
                    split=split_by_id[notice.doc_id],
                    stage=finding.stage,
                    rule_id=finding.rule_id,
                    severity=finding.severity,
                    confidence=finding.confidence,
                    start=finding.start,
                    end=finding.end,
                    codepoint=finding.codepoint,
                    unicode_name=finding.unicode_name,
                    occurrence_count=finding.occurrence_count,
                    detail_code=finding.detail_code,
                )
                anomaly_rows.append(row)
                findings_by_id[notice.doc_id].append(finding)
        for doc_id in replay_summary.get("text_mismatch_doc_ids", []):
            notice = notice_by_id[doc_id]
            finding = TextFinding(
                "replay.prepared_text_hash_mismatch",
                "preprocessing_replay",
                "critical",
                "high",
                None,
                None,
                None,
                None,
                1,
                "text_hash_mismatch",
            )
            row = PreprocessingAnomaly(
                doc_id=notice.doc_id,
                text_sha256=_text_hash(notice.text),
                source_type=notice.source_type,
                split=split_by_id[notice.doc_id],
                stage=finding.stage,
                rule_id=finding.rule_id,
                severity=finding.severity,
                confidence=finding.confidence,
                start=None,
                end=None,
                occurrence_count=1,
                detail_code=finding.detail_code,
            )
            anomaly_rows.append(row)
            findings_by_id[notice.doc_id].append(finding)
        for doc_id in replay_summary.get("snapshot_empty_attachment_doc_ids", []):
            notice = notice_by_id[doc_id]
            finding = TextFinding(
                "replay.url_metadata_missing_in_snapshot",
                "snapshot_serialization",
                "review",
                "high",
                None,
                None,
                None,
                None,
                1,
                "attachments_empty_while_replay_found_text_urls",
            )
            anomaly_rows.append(
                PreprocessingAnomaly(
                    doc_id=notice.doc_id,
                    text_sha256=_text_hash(notice.text),
                    source_type=notice.source_type,
                    split=split_by_id[notice.doc_id],
                    stage=finding.stage,
                    rule_id=finding.rule_id,
                    severity=finding.severity,
                    confidence=finding.confidence,
                    start=None,
                    end=None,
                    occurrence_count=1,
                    detail_code=finding.detail_code,
                )
            )
            findings_by_id[notice.doc_id].append(finding)
        _write_jsonl(temporary / "anomalies.jsonl", anomaly_rows)
        flagged = set(findings_by_id)
        random_sample = _sample_review(notices, flagged, seed)
        random_ids = {notice.doc_id for rows in random_sample.values() for notice in rows}
        queue = []
        for notice in notices:
            if notice.doc_id in flagged:
                method = "flagged"
                relevant = findings_by_id[notice.doc_id]
            elif notice.doc_id in random_ids:
                method = "random_stratified"
                relevant = []
            else:
                continue
            queue.append(
                LMAuditReviewItem(
                    doc_id=notice.doc_id,
                    text_sha256=_text_hash(notice.text),
                    source_type=notice.source_type,
                    split=split_by_id[notice.doc_id],
                    selection_method=method,
                    strata=review_stratum(notice),
                    findings=[
                        AuditReviewFinding(
                            rule_id=f.rule_id,
                            stage=f.stage,
                            start=f.start,
                            end=f.end,
                            severity=f.severity,
                        )
                        for f in relevant
                    ],
                    text=notice.text,
                    status="pending",
                    decision=None,
                    reason=None,
                    reviewer_id=None,
                    reviewed_at=None,
                )
            )
        _write_jsonl(temporary / "review_queue.jsonl", queue)

        # URL summary counts occurrences and per-document unique links without storing values.
        url_summary = []
        for model in model_specs:
            for template_id in selected_templates:
                for policy in POLICIES:
                    for source in ("email", "web"):
                        for split in (
                            "train",
                            "validation",
                            "test",
                            "domain_test",
                            "excluded",
                            "unassigned",
                        ):
                            for synthetic in (False, True):
                                records = [
                                    row
                                    for row in url_rows
                                    if row["model_key"] == model["key"]
                                    and row["template_id"] == template_id
                                    and row["policy"] == policy
                                    and row["source_type"] == source
                                    and row["split"] == split
                                    and row["synthetic"] == synthetic
                                ]
                                url_summary.append(
                                    {
                                        "model_key": model["key"],
                                        "template_id": template_id,
                                        "policy": policy,
                                        "source_type": source,
                                        "split": split,
                                        "synthetic": synthetic,
                                        "url_occurrences": len(records),
                                        "unique_urls_within_document": len(
                                            {
                                                (row["doc_id"], row["document_url_id"])
                                                for row in records
                                            }
                                        ),
                                        "retained_occurrences": sum(
                                            row["retention"] == "retained" for row in records
                                        ),
                                        "partial_occurrences": sum(
                                            row["retention"] == "partial" for row in records
                                        ),
                                        "lost_occurrences": sum(
                                            row["retention"] == "lost" for row in records
                                        ),
                                        "documents_with_urls": len(
                                            {row["doc_id"] for row in records}
                                        ),
                                        "documents_with_any_url_lost": len(
                                            {
                                                row["doc_id"]
                                                for row in records
                                                if row["retention"] != "retained"
                                            }
                                        ),
                                    }
                                )
        _write_csv(temporary / "url_summary.csv", url_summary)

        policy_selection = _select_policies(summary_rows, url_summary, evidence_rows)
        _json(temporary / "policy_selection.json", policy_selection)

        policy_rows = []
        for summary in summary_rows:
            row = dict(summary)
            selected = policy_selection.get(row["model_key"], {})
            row["selected_on_train_validation"] = (
                row["template_id"] == "text_only_v1"
                and row["source_type"] == "email"
                and not row["synthetic"]
                and row["split"] in {"train", "validation"}
                and row["policy"] == selected.get("selected_policy")
            )
            row["selection_score"] = (
                selected.get("selected_score") if row["selected_on_train_validation"] else None
            )
            url_stats = next(
                (
                    item
                    for item in url_summary
                    if (
                        item["model_key"],
                        item["template_id"],
                        item["policy"],
                        item["source_type"],
                        item["split"],
                        item["synthetic"],
                    )
                    == (
                        row["model_key"],
                        row["template_id"],
                        row["policy"],
                        row["source_type"],
                        row["split"],
                        row["synthetic"],
                    )
                ),
                None,
            )
            if url_stats:
                row.update(
                    {
                        f"url_{key}": value
                        for key, value in url_stats.items()
                        if key
                        not in {
                            "model_key",
                            "template_id",
                            "policy",
                            "source_type",
                            "split",
                            "synthetic",
                        }
                    }
                )
            evidence_stats = [
                item
                for item in evidence_rows
                if (
                    item["model_key"],
                    item["template_id"],
                    item["policy"],
                    item["source_type"],
                    item["split"],
                    item["synthetic"],
                )
                == (
                    row["model_key"],
                    row["template_id"],
                    row["policy"],
                    row["source_type"],
                    row["split"],
                    row["synthetic"],
                )
                and item["status"] == "measured"
            ]
            row["evidence_units"] = sum(item["units_total"] for item in evidence_stats)
            row["evidence_fully_visible"] = sum(item["fully_visible"] for item in evidence_stats)
            row["evidence_not_co_visible"] = sum(item["not_co_visible"] for item in evidence_stats)
            policy_rows.append(row)
        _write_csv(temporary / "policy_comparison.csv", policy_rows)

        _render_figures(temporary, token_rows, summary_rows)
        now = datetime.now(UTC).isoformat()
        file_hashes = {path.name: _sha256(path) for path in input_paths}
        lock_path = Path("uv.lock")
        source_path = Path("src/lm_audit.py")
        code_paths = [
            Path("src/cli.py"),
            Path("src/io.py"),
            source_path,
            Path("src/labeling/validation.py"),
            Path("src/preprocessing/links.py"),
            Path("src/preprocessing/split.py"),
            Path("src/preprocessing/text_audit.py"),
            Path("src/preprocessing/token_audit.py"),
            Path("src/schemas.py"),
        ]
        run = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": now,
            "command": sys.argv,
            "snapshot_record_count": len(notices),
            "snapshot_files": file_hashes,
            "input_paths_basename": [path.name for path in input_paths],
            "code_sha256": _sha256(source_path),
            "code_files_sha256": {path.as_posix(): _sha256(path) for path in code_paths},
            "lock_sha256": _sha256(lock_path),
            "audit_split_assignments_sha256": _sha256(split_path),
            "git_head": subprocess.run(
                ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip(),
            "git_status_at_run": subprocess.run(
                ["git", "status", "--short"], check=True, capture_output=True, text=True
            ).stdout.splitlines(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "runtime_versions": {
                package: version(package)
                for package in (
                    "huggingface-hub",
                    "matplotlib",
                    "pydantic",
                    "sentencepiece",
                    "tokenizers",
                )
            },
            "seed": seed,
            "default_seed": DEFAULT_SEED,
            "similarity_threshold": similarity,
            "audit_split": (
                "generated separately for the full current snapshot; the historical "
                "2026-11-04 split is partial and is reference-only"
            ),
            "baseline_split_path": reference_splits_path.name if reference_splits_path else None,
            "baseline_split_rows": len(baseline_map),
            "baseline_split_coverage": sum(doc_id in baseline_map for doc_id in ids),
            "historical_preprocess_comparison": historical_match,
            "model_limits": {spec["key"]: spec["limit"] for spec in model_specs},
            "template_sha256": {
                name: {spec["key"]: spec["template_sha"][name] for spec in model_specs}
                for name in selected_templates
            },
            "selected_templates": selected_templates,
            "policy_selection": policy_selection,
            "raw_replay": replay_summary,
            "model_weights": "not_downloaded; tokenizer-only run",
            "annotation_valid_records": len(valid_annotations),
            "annotation_invalid_records": annotation_failures,
            "human_review_status": "pending; no decisions were supplied or made by this audit",
            "privacy": (
                "Private artifacts, including the human-review queue, stay under the "
                "Git-ignored reports/generated/ path."
            ),
        }
        _json(temporary / "run.json", run)
        _write_report(
            temporary,
            run,
            model_specs,
            token_rows,
            summary_rows,
            url_summary,
            evidence_rows,
            anomaly_rows,
            queue,
            notices,
            valid_annotations,
            manifest_checks,
        )
        _write_progress(
            temporary,
            run,
            len(notices),
            len(model_specs),
            len(valid_annotations),
            len(anomaly_rows),
            len(queue),
        )
        temporary.rename(output_dir)
        return {
            "run_id": run_id,
            "output_dir": str(output_dir),
            "documents": len(notices),
            "valid_annotations": len(valid_annotations),
            "anomaly_findings": len(anomaly_rows),
            "pending_review_items": len(queue),
        }
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_progress(
    output: Path, run: dict, docs: int, models: int, annotations: int, anomalies: int, queued: int
) -> None:
    """Write resumable milestone checkpoints inside the private run."""
    (output / "progress.md").write_text(
        f"""# Tiến độ audit `{run["run_id"]}`

- Mốc 1 — snapshot: hoàn tất, {docs} tài liệu schema hợp lệ; split riêng ở
  `split_assignments.jsonl`.
- Mốc 2 — tokenizer: hoàn tất cho {models} model; chi tiết/file hash ở `model_checks.json`.
- Mốc 3 — context/URL/evidence: xem `context_summary.csv`, `url_summary.csv`,
  `evidence_coverage.csv`.
- Mốc 4 — preprocessing: {anomalies} heuristic finding; queue có {queued} tài liệu, đều pending.
- Mốc 5 — báo cáo: bảng/biểu đồ hoàn tất; xem raw replay trong `preprocessing_replay.json`.
- Nhãn hợp lệ dùng cho coverage: {annotations}; đây không phải adjudication độc lập.

Tiếp theo: nhóm review `review_queue.jsonl`, xác nhận lỗi/false positives; raw bổ sung
cần replay ở run riêng.
""",
        encoding="utf-8",
    )


def _write_report(
    output: Path,
    run: dict,
    models: list[dict],
    token_rows: list[dict],
    summaries: list[dict],
    url_summaries: list[dict],
    evidence_rows: list[dict],
    anomalies: list,
    queue: list,
    notices: list[Notice],
    annotations: dict,
    manifests: dict,
) -> None:
    """Write the Vietnamese report from stored audit tables and aggregates."""
    notice_by_id = {notice.doc_id: notice for notice in notices}
    annotated_email_count = sum(
        notice_by_id[doc_id].source_type == "email" for doc_id in annotations
    )
    replay = run["raw_replay"]
    synthetic_count = sum(notice.synthetic for notice in notices)
    email_count = sum(notice.source_type == "email" for notice in notices)
    web_count = sum(notice.source_type == "web" for notice in notices)
    sections = [
        "# Báo cáo audit LM, context và preprocessing SmartNotice",
        f"\nRun: `{run['run_id']}` · thời điểm UTC: `{run['created_at']}`.",
        "\n## Snapshot và khả năng tái lập",
        (
            f"\nSnapshot có **{len(notices)}** tài liệu nghiên cứu: **{email_count} email**, "
            f"**{web_count} web**; synthetic = {synthetic_count}. Mọi record qua `Notice` "
            f"schema và ID duy nhất. Có **{len(annotations)}** annotation người hợp lệ qua "
            "kiểm tra offset/link; chưa có adjudication độc lập."
        ),
        (
            f"\nTokenizer revision và file hashes ở [`model_checks.json`](model_checks.json); "
            f"input/code/lock hashes, seed `{run['seed']}`, similarity "
            f"`{run['similarity_threshold']}` và lệnh thật ở [`run.json`](run.json). "
            "Split audit mới được tạo cho toàn snapshot. Split lịch sử có "
            f"{run['baseline_split_coverage']}/{len(notices)} tài liệu và chỉ tham chiếu; "
            "không bị thay đổi. Tài liệu `domain_test`: **0**."
        ),
        (
            "\nSnapshot là email/web notices từ `updated_label` cùng "
            "`human_annotations.valid`. Email text khớp "
            f"{run['historical_preprocess_comparison']['text_hash_matches']}/"
            f"{run['historical_preprocess_comparison']['records']} bản email trong "
            "preprocessing 2026-11-04. Web chưa có trong split lịch sử email. "
            "Manifest text-hash đối soát ở [`provenance_reconciliation.json`]"
            "(provenance_reconciliation.json)."
        ),
        "\n## Model, tokenizer và input template",
        (
            "\n- **BamiBERT** `Qualcomm-AI-Research/BamiBERT`, revision "
            "`57bc1340debbe4e348ec549047a763caebe4a977`, context theo yêu cầu là "
            "2.048 token; [model card chính thức](https://huggingface.co/"
            "Qualcomm-AI-Research/BamiBERT).\n"
            "- **ViT5** `VietAI/vit5-base`, revision "
            "`2209a38d735ede63e88f5aa52bcdc11a05a37b85`, encoder budget 1.024; "
            "[repo chính thức](https://github.com/vietai/ViT5). Base là giả định vì "
            "code/run metadata không chọn base hay large.\n"
            "- `text_only_v1` là baseline; `proposed_event_v1` là tiền tố tiếng Việt "
            "được version hóa để so sánh, chưa phải template training của nhóm.\n"
            "- Chỉ tải tokenizer/config; weights không tải. Smoke test model `not_run`. "
            "ViT5 tokenizer count khớp SentencePiece trên 4 fixture tổng hợp; chuỗi ID khác "
            "một lần ở input NFD, nhưng độ dài token khớp. Budget là tổng token encoder input, "
            "gồm special tokens. Repo chưa có caller training/inference cho hai model. "
            "NLI profile pair và ViT5 decoder target là `not_evaluable`: thiếu input/template "
            "chuẩn hóa."
        ),
        "\n## Độ dài token và mail vượt context",
        (
            "\nBảng dưới dùng `text_only_v1` và `simulated_head_truncation`; `overflow` "
            "có mẫu số toàn bộ email đo được. `P95` là input đầy đủ, kể cả special tokens."
        ),
        _report_model_table(models, summaries, token_rows),
        (
            "\nPhân vị theo model/template/source/split/synthetic ở "
            "[`context_summary.csv`](context_summary.csv); từng tài liệu ở "
            "[`token_lengths.csv`](token_lengths.csv). `keep_if_fits` ghi overflow là "
            "`unhandled_overflow` (không có input được gửi); head là mô phỏng lấy đầu. "
            "Không có policy drop riêng; số document `dropped` theo policy nằm trong CSV. "
            "Overflow không có nghĩa parser lỗi."
        ),
        "\n### Kết quả theo nguồn và split",
        (
            "\nBảng dưới là tài liệu nghiên cứu (`synthetic=false`), budget gồm prefix/special "
            "tokens. URL dùng baseline `text_only_v1` với `simulated_head_truncation`; `0/0` "
            "cho biết split rỗng, không phải mẫu số bị thiếu."
        ),
        _report_split_table(models, token_rows, summaries, url_summaries),
        "\n## URL trong nội dung model nhận",
        (
            "\nBảng dùng `text_only_v1` và policy `simulated_head_truncation`, vì repository "
            "chưa có caller training/inference cho hai model. URL được trích từ prepared text "
            "theo matcher/punctuation hiện có, giữ occurrence lặp và canonical ID theo tài liệu; "
            "cột URL duy nhất là tổng số URL canonical riêng trong từng document; raw URL "
            "không ghi trong bảng/report. "
            "`attachments` là metadata riêng: thiếu metadata không có nghĩa URL biến mất "
            "khỏi model input trong `text`."
        ),
        _report_url_table(url_summaries),
        (
            "\n`url_summary.csv` đếm occurrence, URL canonical duy nhất trong tài liệu và "
            "email có URL không còn nguyên. `url_retention.jsonl` lưu hash/offset và "
            "retained/partial/lost theo occurrence, model, template, policy. Đây là mất "
            "do context; không quy cho parser/privacy nếu không có raw replay bằng chứng."
        ),
        "\n## Coverage nhãn",
        (
            f"\nCó {len(annotations)} tài liệu annotation hợp lệ ({annotated_email_count} email). "
            "Coverage span theo label, TIME/DEADLINE, ACTION–argument relation và "
            "event/evidence ở [`evidence_coverage.csv`](evidence_coverage.csv). Đây là "
            "khả năng đồng hiện context trên annotation người chưa adjudicate, không phải "
            "recall/F1. Group không có nhãn là `not_evaluable`."
        ),
        "\n## Bất thường preprocessing và human-review queue",
        (
            f"\nTìm thấy **{len(anomalies)} finding heuristic** trên prepared text, thuộc "
            f"**{len({row.doc_id for row in anomalies})} tài liệu**; queue có **{len(queue)}** "
            "mục, tất cả `pending` (flagged + mẫu ngẫu nhiên phân tầng nguồn/độ dài/URL). "
            "Không ghi nhận người review/adjudicate. Ledger ở "
            "[`anomalies.jsonl`](anomalies.jsonl); văn bản cần xem chỉ ở private "
            "[`review_queue.jsonl`](review_queue.jsonl).\n\n"
        )
        + _report_anomaly_table(anomalies),
        _report_unicode_checks(anomalies, notices),
        (
            "\nRule Unicode gồm U+FFFD, control/invisible/bidi, NFC và non-BMP cần kiểm tra "
            "offset; structural heuristics bắt HTML/MIME/entity/mojibake/lặp dòng/ngắt dòng. "
            "Dấu tiếng Việt, combining mark hợp lệ, emoji, ký tự ngoài ASCII không tự là lỗi. "
            "Mỗi finding chỉ là ứng viên, không phải lỗi đã xác nhận."
        ),
        (
            f"\n**Replay preprocessing:** {replay['available_raw_email_records']}/"
            f"{replay['current_email_records']} raw email đã replay từ MIME. Raw hash khớp "
            f"{replay['raw_hash_matches']}/{replay['matched_doc_ids']}; prepared text hash "
            f"khớp {replay['prepared_text_hash_matches']}/{replay['matched_doc_ids']}; "
            f"sentence offsets khớp {replay['sentence_offset_matches']}/"
            f"{replay['matched_doc_ids']}. "
            f"{replay['current_email_records'] - replay['available_raw_email_records']} "
            "raw email không có trong Drive raw folder; "
            "không có raw HTML nên web replay chưa chạy. Chi tiết ở "
            "[`preprocessing_replay.json`](preprocessing_replay.json). Metadata "
            f"`attachments` khớp {replay['metadata_attachments_matches']}/"
            f"{replay['matched_doc_ids']}. Trong số đó, "
            f"{len(replay['snapshot_empty_attachment_doc_ids'])} "
            f"email có URL trong text nhưng metadata `attachments` rỗng; replay tìm thấy "
            f"{replay['replay_attachment_entries']} URL entries trong metadata. Đây là "
            "finding serialization cần người xem, không phải URL mất với model: "
            f"{replay['prepared_text_hash_matches']} prepared-text hash đều khớp. "
            "Parser warning count ở `snapshot_validation.json`."
        ),
        "\n## Chính sách văn bản dài",
        (
            "\nSo sánh baseline nếu vừa, head truncation, và token windows overlap 0/64/128. "
            "Window lặp prefix và đếm lại toàn input gồm special tokens; offsets là Python "
            "code points. Mỗi window ở [`windows.jsonl`](windows.jsonl); overlap được hợp "
            "coverage trước khi tính span/URL."
        ),
        _recommendations(run.get("policy_selection", {})),
        (
            "\nChính sách được chọn chỉ trên email train/validation theo `policy_selection.json`; "
            "test/domain_test không dùng để chọn. Đóng băng trước held-out evaluation. "
            "Không có latency/RAM nên không suy ra throughput."
        ),
        "\n## Sáu câu hỏi và kết luận",
        (
            "\n1. Phân bố token: percentile theo model/nguồn/split/synthetic/template trong "
            "`context_summary.csv`.\n"
            "2. Mail overflow/cắt/bỏ: tách `unhandled_overflow`, `partial`, `dropped`, mẫu số.\n"
            "3. URL: occurrence, URL duy nhất theo tài liệu, retained/partial/lost.\n"
            "4. Evidence: annotation hợp lệ; thiếu nhãn ghi `not_evaluable`.\n"
            f"5. Preprocessing: replay {replay['available_raw_email_records']}/"
            f"{replay['current_email_records']} email; {replay['prepared_text_hash_matches']} "
            "text hash khớp; raw web không có. Semantic warnings chờ human review.\n"
            "6. Văn bản dài: chính sách chọn trên train/validation; coverage/chi phí lưu "
            "trong `policy_selection.json` và `policy_comparison.csv`."
        ),
        "\n## Tệp và lệnh tái chạy",
        (
            "\n- [`run.json`](run.json), [`model_checks.json`](model_checks.json), "
            "[`snapshot_validation.json`](snapshot_validation.json), "
            "[`preprocessing_replay.json`](preprocessing_replay.json), "
            "[`provenance_reconciliation.json`](provenance_reconciliation.json)\n"
            "- [`token_lengths.csv`](token_lengths.csv), "
            "[`context_summary.csv`](context_summary.csv), [`url_summary.csv`](url_summary.csv), "
            "[`url_retention.jsonl`](url_retention.jsonl), "
            "[`evidence_coverage.csv`](evidence_coverage.csv)\n"
            "- [`anomalies.jsonl`](anomalies.jsonl), [`review_queue.jsonl`](review_queue.jsonl), "
            "[`policy_comparison.csv`](policy_comparison.csv), "
            "[`policy_selection.json`](policy_selection.json), [`windows.jsonl`](windows.jsonl), "
            "[`progress.md`](progress.md), [biểu đồ](figures/)"
        ),
        (
            f"\nLệnh đã chạy: `{' '.join(run['command'])}`. Tài liệu: "
            "[BamiBERT](https://huggingface.co/Qualcomm-AI-Research/BamiBERT), "
            "[ViT5](https://github.com/vietai/ViT5)."
        ),
    ]
    (output / "report.md").write_text("\n".join(sections) + "\n", encoding="utf-8")


def _report_model_table(models: list[dict], summaries: list[dict], token_rows: list[dict]) -> str:
    """Format concise email results with explicit denominators."""
    lines = [
        "\n| Model | N email | P95 | Overflow | Head partial | Token nguồn mất (head) | "
        "Không gửi (keep_if_fits) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in models:
        key = model["key"]
        rows = [
            r
            for r in summaries
            if r["model_key"] == key
            and r["template_id"] == "text_only_v1"
            and r["source_type"] == "email"
            and not r["synthetic"]
        ]
        n = sum(r["documents"] for r in rows if r["policy"] == "simulated_head_truncation")
        all_token_rows = [
            r
            for r in token_rows
            if r["model_key"] == key
            and r["template_id"] == "text_only_v1"
            and r["source_type"] == "email"
            and not r["synthetic"]
        ]
        p95 = _percentile([r["input_tokens"] for r in all_token_rows], 0.95) or 0
        overflow = sum(r["overflow"] for r in all_token_rows)
        partial = sum(
            r["partial_documents"] for r in rows if r["policy"] == "simulated_head_truncation"
        )
        unhandled = sum(
            r["unhandled_overflow_documents"] for r in rows if r["policy"] == "keep_if_fits"
        )
        lost_tokens = sum(
            r["source_tokens_lost_head"] for r in rows if r["policy"] == "simulated_head_truncation"
        )
        lines.append(
            f"| {model['key']} · C={model['limit']:,} | {n} | {p95:,} | "
            f"{overflow}/{n} | {partial}/{n} | {lost_tokens} | {unhandled}/{n} |"
        )
    return "\n".join(lines)


def _report_url_table(rows: list[dict]) -> str:
    """Format URL counts for both models under baseline/head context handling."""
    lines = [
        "\n| Model | N URL occurrence | URL duy nhất/doc | URL retained | Partial | Lost | "
        "Mail có URL mất / có URL |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("bami", "vit5"):
        selected = [
            r
            for r in rows
            if r["model_key"] == key
            and r["template_id"] == "text_only_v1"
            and r["policy"] == "simulated_head_truncation"
            and r["source_type"] == "email"
        ]
        if selected:
            totals = {
                field: sum(row[field] for row in selected)
                for field in (
                    "url_occurrences",
                    "unique_urls_within_document",
                    "retained_occurrences",
                    "partial_occurrences",
                    "lost_occurrences",
                    "documents_with_any_url_lost",
                    "documents_with_urls",
                )
            }
            lines.append(
                f"| {key} | {totals['url_occurrences']} | "
                f"{totals['unique_urls_within_document']} | {totals['retained_occurrences']} | "
                f"{totals['partial_occurrences']} | {totals['lost_occurrences']} | "
                f"{totals['documents_with_any_url_lost']}/{totals['documents_with_urls']} |"
            )
    return "\n".join(lines)


def _report_split_table(
    models: list[dict],
    token_rows: list[dict],
    summaries: list[dict],
    url_summaries: list[dict],
) -> str:
    """Format context and URL retention counts by model, source, and split."""
    lines = [
        "\n| Model | Nguồn | Split | N | P95 input | Overflow n/N | Head partial n/N | "
        "Không gửi n/N | URL retained/partial/lost | Mail URL mất/có URL |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in models:
        for source in ("email", "web"):
            for split in ("train", "validation", "test", "domain_test"):
                records = [
                    row
                    for row in token_rows
                    if row["model_key"] == model["key"]
                    and row["template_id"] == "text_only_v1"
                    and row["source_type"] == source
                    and row["split"] == split
                    and not row["synthetic"]
                ]
                n = len(records)
                p95 = _percentile([row["input_tokens"] for row in records], 0.95)
                selected = [
                    row
                    for row in summaries
                    if row["model_key"] == model["key"]
                    and row["template_id"] == "text_only_v1"
                    and row["source_type"] == source
                    and row["split"] == split
                    and not row["synthetic"]
                ]
                head_partial = sum(
                    row["partial_documents"]
                    for row in selected
                    if row["policy"] == "simulated_head_truncation"
                )
                unhandled = sum(
                    row["unhandled_overflow_documents"]
                    for row in selected
                    if row["policy"] == "keep_if_fits"
                )
                url_rows = [
                    row
                    for row in url_summaries
                    if row["model_key"] == model["key"]
                    and row["template_id"] == "text_only_v1"
                    and row["policy"] == "simulated_head_truncation"
                    and row["source_type"] == source
                    and row["split"] == split
                    and not row["synthetic"]
                ]
                url_fields = (
                    "retained_occurrences",
                    "partial_occurrences",
                    "lost_occurrences",
                    "documents_with_any_url_lost",
                    "documents_with_urls",
                )
                url_totals = {field: sum(row[field] for row in url_rows) for field in url_fields}
                lines.append(
                    f"| {model['key']} · C={model['limit']:,} | {source} | {split} | {n} | "
                    f"{p95 if p95 is not None else '—'} | "
                    f"{sum(row['overflow'] for row in records)}/{n} | "
                    f"{head_partial}/{n} | {unhandled}/{n} | "
                    f"{url_totals['retained_occurrences']}/"
                    f"{url_totals['partial_occurrences']}/"
                    f"{url_totals['lost_occurrences']} | "
                    f"{url_totals['documents_with_any_url_lost']}/"
                    f"{url_totals['documents_with_urls']} |"
                )
    return "\n".join(lines)


def _report_anomaly_table(anomalies: list) -> str:
    """Summarize rule candidates by source without copying prepared text."""
    counts = Counter((finding.source_type, finding.rule_id) for finding in anomalies)
    lines = ["| Nguồn | Rule | Finding |", "|---|---|---:|"]
    if not counts:
        lines.append("| — | Không có finding heuristic | 0 |")
    for (source, rule_id), count in sorted(counts.items()):
        lines.append(f"| {source} | `{rule_id}` | {count} |")
    return "\n".join(lines)


def _report_unicode_checks(anomalies: list, notices: list[Notice]) -> str:
    """State zero-count character checks alongside the observed code-point flags."""
    rule_counts = Counter(finding.rule_id for finding in anomalies)
    absent_rules = {
        "unicode.replacement_character": "U+FFFD",
        "unicode.non_nfc": "non-NFC text",
        "structure.html_tag_residue": "HTML tag residue",
        "structure.html_entity_residue": "HTML entity residue",
        "privacy.redaction_inside_url": "redaction inside URL",
    }
    absent = [label for rule, label in absent_rules.items() if rule_counts[rule] == 0]
    soft_hyphen = sum(finding.codepoint == "U+00AD" for finding in anomalies if finding.codepoint)
    non_bmp = rule_counts["unicode.non_bmp_offset_review"]
    parser_warnings = sum(bool(notice.parser_warnings) for notice in notices)
    return (
        "\nKhông có finding trong các kiểm tra "
        + ", ".join(absent)
        + f"; parser-warning documents={parser_warnings}. Có {soft_hyphen} vị trí U+00AD "
        + f"(soft hyphen) và {non_bmp} vị trí non-BMP cần kiểm tra offset."
    )


def _recommendations(selections: dict) -> str:
    """Report train/validation policy selections and their measured trade-offs."""
    lines = []
    for key, title in (("bami", "BamiBERT"), ("vit5", "ViT5")):
        selection = selections.get(key, {})
        if not selection:
            lines.append(
                f"- **{title}:** không đủ train/validation record để chọn chính sách; "
                "giữ so sánh mô tả, chưa công bố lựa chọn."
            )
            continue
        metrics = selection["metrics"]
        evidence_metric = (
            ", evidence đầy đủ/co-visible "
            f"{metrics['evidence_numerator']}/{metrics['evidence_denominator']}"
            if metrics["evidence_denominator"]
            else ", evidence không đánh giá được trên train/validation"
        )
        lines.append(
            f"- **{title}:** chọn `{selection['selected_policy']}` chỉ trên train/validation, "
            "email, synthetic=false. "
            f"Điểm coverage = {selection['selected_score']:.3f}; "
            f"text {metrics['character_coverage']:.1%}, "
            f"URL nguyên vẹn {metrics['url_retained']}/{metrics['url_total']}{evidence_metric}; "
            f"chi phí {metrics['input_tokens_total']:,} input tokens qua "
            f"{metrics['documents']} tài liệu / {metrics['window_count']} windows."
        )
    return "\n".join(lines)


def _select_policies(
    summary_rows: list[dict], url_rows: list[dict], evidence_rows: list[dict]
) -> dict:
    """Select the lowest-cost policy at the best mean coverage on train/validation."""
    selections = {}
    for model_key in ("bami", "vit5"):
        candidates = []
        for policy in POLICIES:
            summaries = [
                row
                for row in summary_rows
                if row["model_key"] == model_key
                and row["template_id"] == "text_only_v1"
                and row["policy"] == policy
                and row["source_type"] == "email"
                and row["split"] in {"train", "validation"}
                and not row["synthetic"]
            ]
            docs = sum(row["documents"] for row in summaries)
            if docs == 0:
                continue
            char_total = sum(row["source_characters_total"] for row in summaries)
            char_visible = sum(row["source_characters_visible"] for row in summaries)
            urls = [
                row
                for row in url_rows
                if row["model_key"] == model_key
                and row["template_id"] == "text_only_v1"
                and row["policy"] == policy
                and row["source_type"] == "email"
                and row["split"] in {"train", "validation"}
                and not row["synthetic"]
            ]
            url_total = sum(row["url_occurrences"] for row in urls)
            url_retained = sum(row["retained_occurrences"] for row in urls)
            evidence = [
                row
                for row in evidence_rows
                if row["model_key"] == model_key
                and row["template_id"] == "text_only_v1"
                and row["policy"] == policy
                and row["source_type"] == "email"
                and row["split"] in {"train", "validation"}
                and not row["synthetic"]
                and row["status"] == "measured"
            ]
            evidence_total = sum(row["units_total"] for row in evidence)
            evidence_retained = sum(
                row["units_total"] - row["not_co_visible"]
                if row["unit"] in {"action_argument_relation", "event"}
                else row["fully_visible"]
                for row in evidence
            )
            dimensions = [char_visible / max(1, char_total)]
            if url_total:
                dimensions.append(url_retained / url_total)
            if evidence_total:
                dimensions.append(evidence_retained / evidence_total)
            score = sum(dimensions) / len(dimensions)
            candidates.append(
                {
                    "policy": policy,
                    "score": round(score, 6),
                    "score_dimensions": len(dimensions),
                    "metrics": {
                        "character_coverage": char_visible / max(1, char_total),
                        "url_retained": url_retained,
                        "url_total": url_total,
                        "evidence_numerator": evidence_retained,
                        "evidence_denominator": evidence_total,
                        "input_tokens_total": sum(row["input_tokens_total"] for row in summaries),
                        "window_count": sum(row["window_count"] for row in summaries),
                        "documents": docs,
                    },
                }
            )
        if candidates:
            candidates.sort(
                key=lambda item: (
                    -item["score"],
                    item["metrics"]["input_tokens_total"],
                    item["policy"],
                )
            )
            winner = candidates[0]
            selections[model_key] = {
                "selection_scope": {
                    "template": "text_only_v1",
                    "source_type": "email",
                    "splits": ["train", "validation"],
                    "synthetic": False,
                },
                "selection_rule": (
                    "Maximize the unweighted mean of available character, URL, and "
                    "annotation-evidence coverage dimensions; break ties by lower total "
                    "input tokens. Test/domain_test excluded."
                ),
                "selected_policy": winner["policy"],
                "selected_score": winner["score"],
                "metrics": winner["metrics"],
                "candidate_metrics": candidates,
            }
    return selections
