"""Create invented notices for the candidate pipeline smoke run."""

import argparse
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from smartnotice.io import write_jsonl
from smartnotice.labeling.llm import json_sha256, text_sha256
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.preprocessing.text import segment_sentences
from smartnotice.schemas import Notice, SpanReview

_EXAMPLES = (
    ("train", "email", "K24", "nộp hồ sơ", "25/11/2026", "hồ sơ học bổng", "đã đóng học phí"),
    (
        "train",
        "web",
        "năm nhất",
        "đăng ký học phần",
        "12/12/2026",
        "bản sao căn cước",
        "đã có tài khoản",
    ),
    ("train", "email", "ngành Toán", "gửi biểu mẫu", "8h30", "giấy xác nhận", "đã nộp lệ phí"),
    ("validation", "web", "K25", "bổ sung giấy tờ", "17/12/2026", "đơn đăng ký", "đã đủ tín chỉ"),
    ("test", "email", "K23", "xác nhận tham dự", "03/01/2027", "hồ sơ thực tập", "đã đăng ký"),
    (
        "domain_test",
        "web",
        "ngành Vật lý",
        "hoàn thành khảo sát",
        "09/02/2027",
        "bản sao văn bằng",
        "đã tốt nghiệp",
    ),
)


def main() -> None:
    """Write a fresh grouped snapshot with synthetic annotation and review fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=False)
    assignments = []
    reviews = []
    rows_by_file = defaultdict(list)
    for index, (split, source, audience, action, time, document, condition) in enumerate(_EXAMPLES):
        doc_id = f"candidate-demo-{index}"
        url = "https://example.invalid/form"
        fields = (
            ("Đối tượng", "AUDIENCE", f"sinh viên {audience}"),
            ("Công việc", "ACTION", action),
            ("Hạn nộp", "TIME", time),
            ("Hồ sơ gồm", "DOCUMENT", document),
            ("Kênh thực hiện", "CHANNEL", url),
            ("Điều kiện", "CONDITION", condition),
        )
        text = "\n".join(f"{field}: {value}" for field, _, value in fields)
        text += "\nThông báo đã gửi tuần trước."
        notice = Notice(
            doc_id=doc_id,
            source_type=source,
            source_ref="synthetic",
            raw_sha256=f"{index:064x}",
            reference_date_origin="missing",
            text=text,
            attachments=[url],
            sentences=segment_sentences(text),
            group_id=doc_id,
            domain_holdout=split == "domain_test",
            synthetic=True,
            redaction_count=0,
        )
        spans = []
        for field, label, value in fields:
            start = text.index(f"{field}: ") + len(field) + 2
            spans.append(
                {
                    "span_id": label.lower(),
                    "text": value,
                    "label": label,
                    "start": start,
                    "end": start + len(value),
                }
            )
        annotation = {"doc_id": doc_id, "spans": spans}
        review = SpanReview(
            doc_id=doc_id,
            text_sha256=text_sha256(notice),
            annotation_sha256=json_sha256(annotation),
            reviewer_id="synthetic-fixture",
            reviewed_at=datetime(2026, 11, 24, tzinfo=UTC),
            annotation_origin="independent",
        )
        reviews.append(review.model_dump(mode="json"))
        assignments.append(
            {
                "doc_id": doc_id,
                "group_id": notice.group_id,
                "split": split,
                "text_sha256": text_sha256(notice),
                "seed": DEFAULT_SEED,
            }
        )
        for name, row in (("notices", notice.model_dump(mode="json")), ("annotations", annotation)):
            rows_by_file[output / split / f"{name}.jsonl"].append(row)
    for path, rows in rows_by_file.items():
        write_jsonl(path, rows)
    write_jsonl(output / "assignments.jsonl", assignments)
    write_jsonl(output / "span-reviews.jsonl", reviews)


if __name__ == "__main__":
    main()
