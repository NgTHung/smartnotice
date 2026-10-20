"""Regenerate synthetic fixtures; never read or overwrite participant sources."""

import hashlib
import json
from email.message import EmailMessage
from pathlib import Path

from smartnotice.io import write_jsonl
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.schemas import Annotation, Argument, AudienceConstraint, Event, Span

ROOT = Path(__file__).resolve().parents[1]


def main():
    raw_dir = ROOT / "data/raw/examples"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    emails = [
        (
            "scholarship",
            "Hồ sơ học bổng",
            "Sinh viên K24 ngành CNTT hệ CLC nộp hồ sơ học bổng trước 30/10/2026 qua cổng học vụ.\n"
            "Hồ sơ gồm bảng điểm.\nLiên hệ: demo@example.invalid, MSSV: 24000001.\n"
            "-- \nNguyễn Văn Mẫu\nOn Monday, someone wrote:\nNội dung thư cũ.",
            "scholarship-family",
        ),
        (
            "thesis",
            "Đăng ký bảo vệ",
            "Sinh viên K23, trừ sinh viên đã bảo vệ khóa luận, đăng ký bảo vệ từ 01/11 đến 07/11.\n"
            "Sinh viên nộp đề cương nếu đã hoàn thành học phí tại văn phòng khoa.\n"
            "-- \nBan học vụ",
            "thesis-thread",
        ),
        (
            "briefing",
            "Buổi hướng dẫn học vụ",
            "Sinh viên năm nhất tham dự buổi hướng dẫn học vụ vào 25/10/2026 tại hội trường A.\n"
            "Mang theo thẻ sinh viên để kiểm tra thông tin.\n> Thông tin trích dẫn.",
            "briefing",
        ),
        (
            "scholarship_update",
            "Cập nhật học bổng",
            "Sinh viên K24 ngành CNTT hệ CLC nộp hồ sơ học bổng trước 02/11/2026 qua cổng học vụ.\n"
            "Hồ sơ gồm bảng điểm.\nHạn nộp được gia hạn theo thông báo này.",
            "scholarship-family",
        ),
    ]
    for key, subject, body, group in emails:
        message = EmailMessage()
        message["From"] = "Bộ phận mẫu <office@example.invalid>"
        message["To"] = "Sinh viên mẫu <student@example.invalid>"
        message["Date"] = "Tue, 20 Oct 2026 08:00:00 +0700"
        message["Message-ID"] = f"<{key}@example.invalid>"
        message["Subject"] = subject
        message.set_content(body, charset="utf-8")
        path = raw_dir / f"{key}.eml"
        path.write_bytes(message.as_bytes())
        manifest.append(
            {
                "path": path.name,
                "source_type": "email",
                "source_ref": "synthetic",
                "collected_at": "2026-10-20T01:00:00Z",
                "synthetic": True,
                "consent_ref": "synthetic-no-participant",
                "group_id": group,
            }
        )
    pages = [
        (
            "web_scholarship",
            "Học bổng",
            "<p>Sinh viên K24 ngành CNTT hệ CLC nộp hồ sơ học bổng "
            "trước 30/10/2026 qua cổng học vụ.</p><p>Hồ sơ gồm bảng điểm.</p>",
            "scholarship-family",
            False,
        ),
        (
            "exam",
            "Đăng ký dự thi",
            "<p>Sinh viên K24 đăng ký dự thi qua cổng đào tạo.</p>"
            "<table><tr><th>Công việc</th><th>Bắt đầu</th><th>Hạn chót</th></tr>"
            "<tr><td>Đăng ký</td><td>01/11/2026</td><td>07/11/2026</td></tr></table>",
            "exam-template",
            False,
        ),
        (
            "internship",
            "Thực tập doanh nghiệp",
            "<p>Sinh viên K22 ngành CNTT nộp báo cáo thực tập "
            "trước 15/12/2026 qua hệ thống thực tập.</p>"
            "<p>Đính kèm giấy xác nhận của doanh nghiệp.</p>",
            "internship-holdout",
            True,
        ),
        (
            "library",
            "Tập huấn thư viện",
            "<p>Người học tham gia tập huấn tra cứu tài liệu "
            "vào 05/11/2026 tại thư viện.</p><p>Đăng ký tại quầy trước ngày tổ chức.</p>",
            "library-template",
            False,
        ),
        (
            "appeal",
            "Phúc khảo kết quả",
            "<p>Sinh viên có nhu cầu phúc khảo gửi đơn cho phòng "
            "đào tạo trong tuần này.</p><p>Đơn phải ghi rõ học phần và lý do đề nghị xem xét.</p>",
            "appeal-template",
            False,
        ),
    ]
    for key, title, body, group, holdout in pages:
        html = (
            f'<!doctype html><html lang="vi"><head><meta charset="utf-8">'
            f"<title>{title}</title></head><body><nav>Menu mẫu</nav>"
            f"<article><h1>{title}</h1>{body}</article><footer>Footer mẫu</footer></body></html>"
        )
        path = raw_dir / f"{key}.html"
        path.write_text(html, encoding="utf-8")
        manifest.append(
            {
                "path": path.name,
                "source_type": "web",
                "source_ref": f"https://example.invalid/notices/{key}",
                "collected_at": "2026-10-20T01:00:00Z",
                "synthetic": True,
                "reference_date": "2026-10-20",
                "selector": "article",
                "group_id": group,
                "domain_holdout": holdout,
            }
        )
    write_jsonl(raw_dir / "manifest.jsonl", manifest)
    notices = prepare(raw_dir / "manifest.jsonl", ROOT / "data/interim/demo/notices.jsonl")
    by_key = {
        row["path"].split(".")[0]: notice for row, notice in zip(manifest, notices, strict=True)
    }
    annotations = []

    def annotate(key, definitions, event_definitions, constraint_definitions):
        notice = by_key[key]
        spans = []
        for span_id, label, phrase in definitions:
            start = notice.text.index(phrase)
            spans.append(
                Span(
                    span_id=span_id, label=label, start=start, end=start + len(phrase), text=phrase
                )
            )
        lookup = {span.span_id: span for span in spans}
        events = []
        for action_id, arguments in event_definitions:
            linked = [lookup[action_id], *[lookup[a["span_id"]] for a in arguments]]
            evidence = [
                s.sentence_id
                for s in notice.sentences
                if any(s.start <= span.start and span.end <= s.end for span in linked)
            ]
            events.append(
                Event(
                    event_id=f"e{len(events) + 1}",
                    action_span_id=action_id,
                    arguments=[Argument(**a) for a in arguments],
                    evidence_sentence_ids=evidence,
                )
            )
        annotations.append(
            Annotation(
                doc_id=notice.doc_id,
                annotator_id="synthetic-author",
                spans=spans,
                events=events,
                audience_constraints=[AudienceConstraint(**c) for c in constraint_definitions],
            )
        )

    annotate(
        "scholarship",
        [
            ("a1", "ACTION", "nộp hồ sơ học bổng"),
            ("u1", "AUDIENCE", "Sinh viên K24 ngành CNTT hệ CLC"),
            ("t1", "TIME", "30/10/2026"),
            ("c1", "CHANNEL", "cổng học vụ"),
            ("d1", "DOCUMENT", "bảng điểm"),
        ],
        [
            (
                "a1",
                [
                    {"span_id": "u1"},
                    {"span_id": "t1", "role": "DEADLINE", "normalized_date": "2026-10-30"},
                    {"span_id": "c1"},
                    {"span_id": "d1"},
                ],
            )
        ],
        [{"audience_span_id": "u1", "cohorts": ["K24"], "majors": ["CNTT"], "programs": ["CLC"]}],
    )
    annotate(
        "thesis",
        [
            ("a1", "ACTION", "đăng ký bảo vệ"),
            ("a2", "ACTION", "nộp đề cương"),
            ("u1", "AUDIENCE", "Sinh viên K23, trừ sinh viên đã bảo vệ khóa luận"),
            ("t1", "TIME", "01/11"),
            ("t2", "TIME", "07/11"),
            ("k1", "CONDITION", "đã hoàn thành học phí"),
            ("c1", "CHANNEL", "văn phòng khoa"),
        ],
        [
            (
                "a1",
                [
                    {"span_id": "u1"},
                    {
                        "span_id": "t1",
                        "role": "START",
                        "normalized_date": "2026-11-01",
                        "inferred": True,
                    },
                    {
                        "span_id": "t2",
                        "role": "DEADLINE",
                        "normalized_date": "2026-11-07",
                        "inferred": True,
                    },
                ],
            ),
            ("a2", [{"span_id": "u1"}, {"span_id": "k1"}, {"span_id": "c1"}]),
        ],
        [{"audience_span_id": "u1", "cohorts": ["K23"], "excluded_statuses": ["defended"]}],
    )
    annotate(
        "exam",
        [
            ("a1", "ACTION", "đăng ký dự thi"),
            ("u1", "AUDIENCE", "Sinh viên K24"),
            ("c1", "CHANNEL", "cổng đào tạo"),
            ("t1", "TIME", "01/11/2026"),
            ("t2", "TIME", "07/11/2026"),
        ],
        [
            (
                "a1",
                [
                    {"span_id": "u1"},
                    {"span_id": "c1"},
                    {"span_id": "t1", "role": "START", "normalized_date": "2026-11-01"},
                    {"span_id": "t2", "role": "DEADLINE", "normalized_date": "2026-11-07"},
                ],
            )
        ],
        [{"audience_span_id": "u1", "cohorts": ["K24"]}],
    )
    annotate(
        "briefing",
        [
            ("a1", "ACTION", "tham dự buổi hướng dẫn học vụ"),
            ("u1", "AUDIENCE", "Sinh viên năm nhất"),
            ("t1", "TIME", "25/10/2026"),
            ("c1", "CHANNEL", "hội trường A"),
            ("d1", "DOCUMENT", "thẻ sinh viên"),
        ],
        [
            (
                "a1",
                [
                    {"span_id": "u1"},
                    {"span_id": "c1"},
                    {"span_id": "d1"},
                    {"span_id": "t1", "role": "EVENT_TIME", "normalized_date": "2026-10-25"},
                ],
            )
        ],
        [{"audience_span_id": "u1", "cohorts": ["K26"]}],
    )
    annotate(
        "internship",
        [
            ("a1", "ACTION", "nộp báo cáo thực tập"),
            ("u1", "AUDIENCE", "Sinh viên K22 ngành CNTT"),
            ("t1", "TIME", "15/12/2026"),
            ("c1", "CHANNEL", "hệ thống thực tập"),
            ("d1", "DOCUMENT", "giấy xác nhận của doanh nghiệp"),
        ],
        [
            (
                "a1",
                [
                    {"span_id": "u1"},
                    {"span_id": "c1"},
                    {"span_id": "d1"},
                    {"span_id": "t1", "role": "DEADLINE", "normalized_date": "2026-12-15"},
                ],
            )
        ],
        [{"audience_span_id": "u1", "cohorts": ["K22"], "majors": ["CNTT"]}],
    )
    write_jsonl(
        ROOT / "data/annotations/examples/events.jsonl",
        [a.model_dump(mode="json") for a in annotations],
    )
    profiles = [
        {
            "profile_id": "p1",
            "cohort": "K24",
            "major": "CNTT",
            "program": "CLC",
            "status": "active",
        },
        {"profile_id": "p2", "cohort": "K23", "major": "CNTT", "program": "CQ", "status": "active"},
        {
            "profile_id": "p3",
            "cohort": "K23",
            "major": "CNTT",
            "program": "CQ",
            "status": "defended",
        },
        {"profile_id": "p4", "cohort": "K22", "major": "CNTT", "program": "CQ", "status": "active"},
        {"profile_id": "p5", "cohort": None, "major": "CNTT", "program": None, "status": None},
    ]
    write_jsonl(ROOT / "data/annotations/examples/profiles.jsonl", profiles)
    index = {
        row["path"]: hashlib.sha256((raw_dir / row["path"]).read_bytes()).hexdigest()
        for row in manifest
    }
    (raw_dir / "checksums.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(manifest)} synthetic notices and {len(annotations)} annotations")


if __name__ == "__main__":
    main()
