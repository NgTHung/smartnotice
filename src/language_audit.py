"""Extend a recorded LM audit with label imbalance and surface-form statistics."""

import json
import platform
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import get_args

from smartnotice.io import read_jsonl
from smartnotice.labeling.token_balance import token_label_counts
from smartnotice.labeling.validation import validate_annotation
from smartnotice.lm_audit import _json, _sha256, _text_hash, _write_csv, _write_jsonl
from smartnotice.preprocessing.language_features import (
    ABBREVIATIONS,
    ENGLISH_WORDS,
    RULE_VERSION,
    UNACCENTED_PHRASES,
    language_features,
    surface_words,
)
from smartnotice.schemas import (
    Annotation,
    LanguageDocumentStats,
    Notice,
    SpanLabel,
    TokenBalanceRow,
)
from tokenizers import Tokenizer

RULES = (
    "known_abbreviation",
    "english_lexicon_hit",
    "unaccented_phrase_candidate",
    "uppercase_line",
    "lowercase_line",
    "ascii_only_line_candidate",
    "mixed_vietnamese_english_candidate",
)


def run_language_audit(
    notice_paths: list[Path],
    annotations_path: Path,
    base_run: Path,
    output_dir: Path,
    cache_dir: Path = Path("data/interim/lm_audit_snapshot/tokenizer_cache"),
) -> dict:
    """Write an atomic, private extension using the base snapshot hashes/splits.

    Existing outputs are rejected. Inputs must match files hashed by base_run;
    annotations and tokenizer resources are validated without network access.
    Counts cover full prepared text, without prefix, padding, or truncation.
    """
    if output_dir.exists():
        raise ValueError("Output already exists; choose a new extension run")
    base = json.loads((base_run / "run.json").read_text(encoding="utf-8"))
    for path in [*notice_paths, annotations_path]:
        if base["snapshot_files"].get(path.name) != _sha256(path):
            raise ValueError(f"Input does not match base snapshot: {path.name}")
    notices = [Notice.model_validate(r) for p in notice_paths for r in read_jsonl(p)]
    by_id = {n.doc_id: n for n in notices}
    if len(notices) != len(by_id):
        raise ValueError("Duplicate notice IDs")
    if base.get("audit_split_assignments_sha256") != _sha256(base_run / "split_assignments.jsonl"):
        raise ValueError("Base split hash differs from run metadata")
    splits = {r["doc_id"]: r["split"] for r in read_jsonl(base_run / "split_assignments.jsonl")}
    if set(splits) != set(by_id):
        raise ValueError("Input IDs differ from base split IDs")
    annotations = {}
    for row in read_jsonl(annotations_path):
        annotation = Annotation.model_validate(row)
        if annotation.doc_id not in by_id or annotation.doc_id in annotations:
            raise ValueError("Annotation ID missing from snapshot or repeated")
        validate_annotation(annotation, by_id[annotation.doc_id])
        annotations[annotation.doc_id] = annotation
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".language-", dir=output_dir.parent))
    try:
        document_rows, findings, queue = [], [], []
        sums, docs, feature_docs, lexicon, vocab = (
            defaultdict(Counter),
            Counter(),
            defaultdict(Counter),
            Counter(),
            defaultdict(Counter),
        )
        for notice in notices:
            group = (notice.source_type, splits[notice.doc_id], notice.synthetic)
            counts, hits = language_features(notice.text)
            document_rows.append(
                LanguageDocumentStats(
                    doc_id=notice.doc_id,
                    text_sha256=_text_hash(notice.text),
                    source_type=notice.source_type,
                    split=group[1],
                    synthetic=notice.synthetic,
                    counts=counts,
                )
            )
            docs[group] += 1
            sums[group].update(counts)
            feature_docs[group].update({h.rule for h in hits})
            vocab[group].update(word.casefold() for word in surface_words(notice.text))
            for hit in hits:
                findings.append(
                    {
                        "doc_id": notice.doc_id,
                        "source_type": notice.source_type,
                        "split": group[1],
                        "synthetic": notice.synthetic,
                        **hit.model_dump(mode="json"),
                        "status": "pending",
                    }
                )
                if hit.lexicon_key:
                    lexicon[(*group, hit.rule, hit.lexicon_key)] += 1
            if hits:
                queue.append(
                    {
                        "doc_id": notice.doc_id,
                        "text_sha256": _text_hash(notice.text),
                        "source_type": notice.source_type,
                        "split": group[1],
                        "rules": sorted({h.rule for h in hits}),
                        "status": "pending",
                        "decision": None,
                        "reviewer_id": None,
                        "reviewed_at": None,
                    }
                )
        _write_jsonl(temp / "document_stats.jsonl", document_rows)
        _write_jsonl(temp / "surface_findings.jsonl", findings)
        _write_jsonl(temp / "review_queue.jsonl", queue)
        surface = []
        vocabulary = []
        for group, n in sorted(docs.items()):
            source, split, synthetic = group
            for rule in RULES:
                unit = "eligible_lines" if "line" in rule or "mixed_" in rule else "words"
                denominator = sums[group][unit]
                surface.append(
                    dict(
                        source_type=source,
                        split=split,
                        synthetic=synthetic,
                        rule=rule,
                        documents=n,
                        affected_documents=feature_docs[group][rule],
                        occurrences=sums[group][rule],
                        denominator=denominator,
                        unit=unit,
                    )
                )
            counts = vocab[group]
            total = counts.total()
            vocabulary.append(
                dict(
                    source_type=source,
                    split=split,
                    synthetic=synthetic,
                    words=total,
                    types=len(counts),
                    hapax_types=sum(c == 1 for c in counts.values()),
                    top10_word_share=sum(c for _, c in counts.most_common(10)) / max(1, total),
                )
            )
        _write_csv(temp / "surface_summary.csv", surface)
        _write_csv(temp / "vocabulary_summary.csv", vocabulary)
        _write_csv(
            temp / "lexicon_counts.csv",
            [
                dict(
                    source_type=k[0],
                    split=k[1],
                    synthetic=k[2],
                    rule=k[3],
                    lexicon_key=k[4],
                    occurrences=v,
                )
                for k, v in sorted(lexicon.items())
            ],
        )
        checks = json.loads((base_run / "model_checks.json").read_text(encoding="utf-8"))
        span_rows = []
        span_counts = Counter()
        span_documents = defaultdict(set)
        for doc_id, annotation in annotations.items():
            notice = by_id[doc_id]
            for span in annotation.spans:
                key = (notice.source_type, splits[doc_id], notice.synthetic, span.label)
                span_counts[key] += 1
                span_documents[key].add(doc_id)
        for key, count in sorted(span_counts.items()):
            span_rows.append(
                dict(
                    source_type=key[0],
                    split=key[1],
                    synthetic=key[2],
                    label=key[3],
                    spans=count,
                    documents=len(span_documents[key]),
                )
            )
        _write_csv(temp / "annotation_span_summary.csv", span_rows)
        balance, token_resources = [], {}
        label_classes = ["O", *get_args(SpanLabel), "BOUNDARY", "MULTI"]
        for model in checks["models"]:
            directory = (
                cache_dir
                / ("models--" + model["model_id"].replace("/", "--"))
                / "snapshots"
                / model["revision"]
            )
            path = directory / "tokenizer.json"
            if _sha256(path) != model["tokenizer_file_sha256"]["tokenizer.json"]:
                raise ValueError("Cached tokenizer hash differs from base run")
            tokenizer = Tokenizer.from_file(str(path))
            tokenizer.no_truncation()
            tokenizer.no_padding()
            token_resources[model["model_key"]] = dict(
                model_id=model["model_id"], revision=model["revision"], sha256=_sha256(path)
            )
            counts_by_group, ann_docs = defaultdict(Counter), Counter()
            encoded_total = 0
            zero_width = 0
            for doc_id, annotation in annotations.items():
                notice = by_id[doc_id]
                group = (notice.source_type, splits[doc_id], notice.synthetic)
                encoded = tokenizer.encode(notice.text, add_special_tokens=False)
                encoded_total += len(encoded.ids)
                zero_width += sum(end <= start for start, end in encoded.offsets)
                counts_by_group[group].update(token_label_counts(encoded.offsets, annotation))
                ann_docs[group] += 1
            token_resources[model["model_key"]]["encoded_tokens"] = encoded_total
            token_resources[model["model_key"]]["excluded_zero_width_tokens"] = zero_width
            for group, counts in sorted(counts_by_group.items()):
                for label in label_classes:
                    balance.append(
                        TokenBalanceRow(
                            model_key=model["model_key"],
                            source_type=group[0],
                            split=group[1],
                            synthetic=group[2],
                            documents=ann_docs[group],
                            label=label,
                            count=counts[label],
                            denominator=counts.total(),
                            share=counts[label] / max(1, counts.total()),
                        ).model_dump(mode="json")
                    )
        _write_csv(temp / "token_label_balance.csv", balance)
        _json(
            temp / "rules.json",
            dict(
                version=RULE_VERSION,
                abbreviations=ABBREVIATIONS,
                english_words=ENGLISH_WORDS,
                unaccented_phrases=UNACCENTED_PHRASES,
            ),
        )
        metadata = dict(
            created_at=datetime.now(UTC).isoformat(),
            python=platform.python_version(),
            runtime_versions={p: version(p) for p in ("tokenizers", "pydantic", "matplotlib")},
            command=sys.argv,
            base_run=str(base_run),
            base_run_sha256=_sha256(base_run / "run.json"),
            split_sha256=_sha256(base_run / "split_assignments.jsonl"),
            inputs={p.name: _sha256(p) for p in [*notice_paths, annotations_path]},
            tokenizer_resources=token_resources,
            rules_sha256=_sha256(temp / "rules.json"),
            code_sha256={
                p: _sha256(Path(p))
                for p in (
                    "src/language_audit.py",
                    "src/preprocessing/language_features.py",
                    "src/labeling/token_balance.py",
                    "src/schemas.py",
                )
            },
            lock_sha256=_sha256(Path("uv.lock")),
            documents=len(notices),
            annotated_documents=len(annotations),
            annotated_source_counts=dict(Counter(by_id[d].source_type for d in annotations)),
            unannotated_documents=len(notices) - len(annotations),
            unannotated_status="not_evaluable",
            review_status="pending",
        )
        _json(temp / "run.json", metadata)
        _figures(temp, balance, surface)
        _report(temp, surface, balance, docs, metadata)
        temp.rename(output_dir)
        return dict(
            output_dir=str(output_dir),
            documents=len(notices),
            annotated_documents=len(annotations),
            annotated_source_counts=dict(Counter(by_id[d].source_type for d in annotations)),
            pending_review_documents=len(queue),
        )
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def _report(output: Path, surface: list, balance: list, docs: Counter, metadata: dict) -> None:
    lines = [
        "# Token-level imbalance và đặc điểm cách viết",
        "",
        (
            f"Snapshot: {metadata['documents']} tài liệu; "
            f"{metadata['annotated_documents']} annotation người hợp lệ, chưa "
            f"adjudicate. Kế thừa hash/split từ base run trong run.json; số đo full prepared text, "
            f"không truncation/prefix/special tokens."
        ),
        "",
        "## Phân bố nhãn ở mức token con",
        "",
        (
            f"O là token không giao span trong annotation đã cung cấp. Chưa có xác nhận "
            f"annotation đầy đủ nên O chưa phải negative gold đã duyệt. BOUNDARY giao "
            f"biên span; MULTI nằm trong nhiều span. Đây là thống kê lớp loại trừ nhau, "
            f"không phải nhãn BIO để train. {metadata['unannotated_documents']} tài "
            f"liệu thiếu annotation không được gán O."
        ),
        "",
    ]
    for model in ("bami", "vit5"):
        lines.extend(
            ["", "| Model | Lớp | Token | Tổng token subset | Tỷ lệ |", "|---|---|---:|---:|---:|"]
        )
        selected = [r for r in balance if r["model_key"] == model and not r["synthetic"]]
        total = sum(r["count"] for r in selected)
        counts = Counter()
        for row in selected:
            counts[row["label"]] += row["count"]
        for label, n in counts.items():
            lines.append(f"| {model} | {label} | {n} | {total} | {n / max(1, total):.2%} |")
        positive = [counts[label] for label in get_args(SpanLabel) if counts[label]]
        missing = [label for label in get_args(SpanLabel) if not counts[label]]
        lines.append(
            (
                f"\n{model}: max/min lớp entity có token = "
                f"{max(positive) / min(positive):.2f}×; lớp entity bằng 0: "
                f"{', '.join(missing) or 'không'}.\n"
            )
            if positive
            else f"\n{model}: không đánh giá được tỷ lệ entity.\n"
        )
    lines.extend(
        [
            "## Đặc điểm email và web",
            "",
            (
                "Từ là chuỗi chữ cái Unicode, không phải từ đã phân đoạn tiếng Việt. Loại "
                "URL, số và placeholder privacy trước đếm. Dòng đủ điều kiện có ít nhất "
                "hai chữ cái. Một mail có thể thuộc nhiều nhóm."
            ),
            "",
            "| Nguồn | Dấu hiệu | Mail/trang bị ảnh hưởng | Occurrence | Mẫu số | Đơn vị |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for source in ("email", "web"):
        n = sum(v for k, v in docs.items() if k[0] == source and not k[2])
        for rule in RULES:
            rows = [
                r
                for r in surface
                if r["source_type"] == source and r["rule"] == rule and not r["synthetic"]
            ]
            affected = sum(r["affected_documents"] for r in rows)
            lines.append(
                f"| {source} | {rule} | {affected}/{n} ({affected / max(1, n):.1%}) | "
                f"{sum(r['occurrences'] for r in rows)} | "
                f"{sum(r['denominator'] for r in rows)} | "
                f"{rows[0]['unit'] if rows else '—'} |"
            )
    lines.extend(
        [
            "",
            "## Diễn giải và review",
            "",
            (
                "known_abbreviation khớp không phân biệt hoa/thường, dùng danh sách cố "
                "định gồm SV/HK/ĐKHP và các dạng "
                "trong rules.json; không phải tất cả viết tắt. ASCII-only không đồng nghĩa "
                "tiếng Việt không dấu: có thể là tiếng Anh, viết tắt hoặc tên. "
                "unaccented_phrase_candidate chỉ khớp danh sách cụm tiếng Việt không dấu. "
                "english_lexicon_hit chỉ khớp từ trong danh sách tiếng Anh; có nhập nhằng "
                "và bỏ sót. mixed_vietnamese_english_candidate cần dấu tiếng Việt và hit "
                "tiếng Anh trên cùng dòng, chưa phải language identification đã duyệt."
            ),
            "",
            (
                "Review queue chỉ chứa ID/hash/rules, không có đoạn corpus. Dùng offsets "
                "trong surface_findings.jsonl đối chiếu đúng prepared text; tất cả "
                "pending, reviewer/decision để trống. Không suy ra lỗi preprocessing từ "
                "một dấu hiệu cách viết. Không đề xuất class weight/resampling từ test; "
                "bảng theo split là mô tả, cần annotation đầy đủ và quyết định training "
                "riêng."
            ),
            "",
            "## Artifact và tái chạy",
            "",
            (
                "Các bảng tách source/split/synthetic: "
                "[surface_summary.csv](surface_summary.csv), "
                "[token_label_balance.csv](token_label_balance.csv), "
                "[lexicon_counts.csv](lexicon_counts.csv), "
                "[vocabulary_summary.csv](vocabulary_summary.csv). "
                "[document_stats.jsonl](document_stats.jsonl), "
                "[surface_findings.jsonl](surface_findings.jsonl), "
                "[review_queue.jsonl](review_queue.jsonl) là artifact private. "
                "[run.json](run.json) ghi hash/command; [rules.json](rules.json) ghi toàn "
                "bộ danh sách luật."
            ),
            "",
            "Lệnh CLI thực chạy: `" + " ".join(metadata["command"]) + "`",
            "",
        ]
    )
    lines.extend(
        ["", "## Viết tắt đã khớp trong email", "", "| Dạng cố định | Occurrence |", "|---|---:|"]
    )
    import csv

    with (output / "lexicon_counts.csv").open(encoding="utf-8", newline="") as file:
        counts = Counter()
        for row in csv.DictReader(file):
            if (
                row["source_type"] == "email"
                and row["synthetic"] == "False"
                and row["rule"] == "known_abbreviation"
            ):
                counts[row["lexicon_key"]] += int(row["occurrences"])
    for key, count in counts.most_common():
        lines.append(f"| {key} | {count} |")
    lines.extend(
        [
            "",
            "![Phân bố nhãn](figures/token_label_balance.png)",
            "",
            "![Cách viết trong email](figures/email_surface_forms.png)",
            "",
        ]
    )
    lines.extend(
        [
            "",
            (
                f"Số token phụ thuộc tokenizer và độ dài span; CHANNEL có nhiều token không "
                f"chứng minh nhiều sự kiện CHANNEL hơn. Đối chiếu [số span theo "
                f"nhãn](annotation_span_summary.csv). O chỉ mô tả phần chưa được span bao "
                f"phủ trong subset đã cung cấp. Các mẫu số token không áp dụng cho "
                f"{metadata['unannotated_documents']} tài liệu còn lại."
            ),
            "",
        ]
    )
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _figures(output: Path, balance: list[dict], surface: list[dict]) -> None:
    """Render only aggregate label and surface-form measurements."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory = output / "figures"
    directory.mkdir()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for axis, model in zip(axes, ("bami", "vit5"), strict=True):
        counts = Counter()
        for row in balance:
            if row["model_key"] == model and not row["synthetic"]:
                counts[row["label"]] += row["count"]
        labels = list(counts)
        axis.barh(labels, [counts[label] for label in labels])
        axis.set_xscale("symlog", linthresh=1)
        axis.set_title(model + " · annotation người hợp lệ")
        axis.set_xlabel("Số token con (thang symlog)")
        for i, label in enumerate(labels):
            axis.annotate(
                str(counts[label]),
                (counts[label], i),
                xytext=(3, 0),
                textcoords="offset points",
                fontsize=8,
            )
        axis.margins(x=0.25)
    fig.savefig(directory / "token_label_balance.png", dpi=160)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    names = [
        "Viết tắt trong danh sách",
        "Từ trong danh sách tiếng Anh",
        "Cụm không dấu ứng viên",
        "Dòng toàn hoa",
        "Dòng toàn thường",
        "Dòng chỉ chữ ASCII",
        "Việt/Anh xen kẽ ứng viên",
    ]
    values = []
    for rule in RULES:
        rows = [
            r
            for r in surface
            if r["source_type"] == "email" and r["rule"] == rule and not r["synthetic"]
        ]
        n = sum(r["documents"] for r in rows)
        values.append(100 * sum(r["affected_documents"] for r in rows) / max(1, n))
    axis.barh(names, values, color="#1b9e77")
    axis.set_xlim(0, 110)
    axis.set_xlabel("Email có dấu hiệu / toàn bộ email nghiên cứu (%)")
    for i, value in enumerate(values):
        axis.text(value + 1, i, f"{value:.1f}%", va="center")
    fig.savefig(directory / "email_surface_forms.png", dpi=160)
    plt.close(fig)
