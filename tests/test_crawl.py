"""Exercise HCMUS collection with synthetic HTML and offline HTTP only."""

import hashlib
import json
import unicodedata

import httpx
import pytest
from smartnotice import cli
from smartnotice.collectors import crawl, web
from smartnotice.collectors.crawl import crawl_web, validate_run_id
from smartnotice.collectors.hcmus import (
    LIST_URL,
    NoticeRejected,
    discover_links,
    parse_detail,
    selection_reason,
)
from smartnotice.collectors.web import CollectionPolicyError, WebCollector
from smartnotice.io import read_jsonl
from smartnotice.schemas import CrawlIndex, CrawlLog, CrawlSummary, Notice


def listing(*paths):
    return (
        "<div class='vc_gitem-post-data-source-post_title'>"
        + "".join(
            f"<a href='{path}'>Thông báo đăng ký học phần {number}</a>"
            for number, path in enumerate(paths)
        )
        + "</div>"
    ).encode()


def detail(
    *,
    title="Thông báo đăng ký học phần",
    body="Sinh viên K24 đăng ký trước ngày 30/10.",
    display="27/10/2026",
    metadata="2026-10-27T01:00:00+07:00",
):
    published = f"<span class='published'>{display}</span>" if display is not None else ""
    meta = f"<meta property='article:published_time' content='{metadata}'>" if metadata else ""
    return (
        f"<html><head><meta charset='utf-8'>{meta}</head><body><article>"
        f"<h1 class='entry-title'>{title}</h1>{published}"
        f"<div class='entry-content'>{body}</div></article></body></html>"
    ).encode()


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(web.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(web.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))


def client_for(pages, requests):
    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        value = pages[str(request.url)]
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, content=value, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "title, reason",
    [
        ("Thông báo đăng ký học phần", "eligible"),
        ("Nộp hồ sơ tốt nghiệp", "eligible"),
        ("Thư mời tham gia hội thảo cho sinh viên", "excluded_title"),
        ("Kết quả học bổng", "excluded_title"),
        ("Danh sách sinh viên", "excluded_title"),
        ("Quy chế học vụ", "excluded_title"),
        ("Chương trình phát triển tài năng bên ngoài", "outside_academic_scope"),
        ("Tuyển chọn sinh viên thực hiện nhiệm vụ chuyển đổi số", "outside_academic_scope"),
        ("Triển khai thử nghiệm website Phòng Công tác Sinh viên", "outside_academic_scope"),
        ("Thông báo nghỉ học đối với sinh viên Khóa 2026", "eligible"),
    ],
)
def test_title_sampling(title, reason):
    assert selection_reason(unicodedata.normalize("NFD", title.upper())) == reason


def test_discovery_normalizes_urls_and_keeps_identifying_queries():
    raw = listing(
        "/notice?newsid=1#first",
        "https://HCMUS.edu.vn:443/notice?newsid=1#second",
        "/notice?newsid=2",
        "../relative",
        "https://outside.invalid/x",
        "javascript:alert(1)",
        "mailto:a@example.invalid",
        "https://user@hcmus.edu.vn/x",
        "https://hcmus.edu.vn:bad/x",
        "https://hcmus.edu.vn:0/other-port",
        "https://[broken/x",
        "/document.pdf?download=1",
        "#top",
    )
    candidates = discover_links(raw, LIST_URL)
    assert [row.url for row in candidates] == [
        "https://hcmus.edu.vn/notice?newsid=1",
        "https://hcmus.edu.vn/notice?newsid=2",
        "https://hcmus.edu.vn/relative",
    ]


def test_discovery_fails_when_selector_changes():
    with pytest.raises(ValueError, match="No detail links"):
        discover_links(b"<a href='/notice'>Other layout</a>", LIST_URL)


@pytest.mark.parametrize(
    "display, metadata, candidate, status",
    [
        ("27/10/2026", "2026-10-26T19:00:00Z", "2026-10-27", "unverified"),
        (None, "2026-10-27T01:00:00+07:00", None, "missing"),
        ("Cập nhật: 27/10/2026", None, None, "invalid"),
        ("31/02/2026", None, None, "invalid"),
        ("27/10/2026", "not a timestamp", "2026-10-27", "invalid"),
        ("27/10/2026", "2026-10-26T01:00:00+07:00", "2026-10-27", "conflict"),
        ("27/10/2026", None, "2026-10-27", "unverified"),
        ("01/01/0001", "0001-01-01T00:00:00+14:00", "0001-01-01", "invalid"),
    ],
)
def test_dates_remain_candidates(display, metadata, candidate, status):
    result = parse_detail(detail(display=display, metadata=metadata))
    assert (str(result.date_candidate) if result.date_candidate else None) == candidate
    assert result.date_status == status


@pytest.mark.parametrize(
    "raw, reason",
    [
        (b"<html>Login or CAPTCHA</html>", "body_selector_mismatch"),
        (detail().replace(b"entry-content", b"changed-layout"), "body_selector_mismatch"),
        (
            detail().replace(b"</article>", b"<div class='entry-content'>Other</div></article>"),
            "body_selector_mismatch",
        ),
        (detail().replace(b"entry-title", b"other-title"), "title_selector_mismatch"),
        (detail(title="Thư mời hội thảo cho sinh viên"), "excluded_title"),
        (
            detail(body="<a href='x.pdf'>Đăng ký học phần tại đây</a><img src='x.png'>"),
            "attachment_only_or_no_action_prose",
        ),
    ],
)
def test_invalid_detail_is_rejected(raw, reason):
    with pytest.raises(NoticeRejected, match=reason):
        parse_detail(raw)


def test_tables_unicode_and_short_action_text_are_preserved():
    result = parse_detail(
        detail(
            body=(
                "<p>Sinh viên đăng ký học phần.</p><table><tr><th>Hạn</th><th>Việc</th></tr>"
                "<tr><td colspan='1'>30/10</td><td>Nộp hồ sơ \ufffd</td></tr></table>"
            )
        )
    )
    assert "Hạn: 30/10; Việc: Nộp hồ sơ" in result.text
    assert result.warnings == ("replacement_character", "merged_table_cells")


@pytest.mark.parametrize(
    "body",
    [
        "Link thông báo: <a href='fees.pdf'>Thông báo nộp học phí</a>"
        " Quyết định mức học phí năm học 2026-2027",
        "Sinh viên xem thời khóa biểu (đã cập nhật) tại link sau: <a href='sheet'>Lịch</a>",
        "Khoa thông báo kế hoạch học thực tập trong file sau: <a href='lab.pdf'>Kế hoạch</a>",
        "Tài liệu học vụ tham khảo. Thông tin liên hệ: "
        "<a href='mailto:test@example.invalid'>Email</a>",
        "Sinh viên Khóa 2026 xem hướng dẫn đăng nhập Portal để đăng ký học phần "
        "trong file đính kèm <a href='guide.pdf'>Hướng dẫn ĐKHP</a>",
    ],
)
def test_attachment_introductions_do_not_count_as_action_prose(body):
    with pytest.raises(NoticeRejected, match="attachment_only_or_no_action_prose"):
        parse_detail(detail(body=body))


def test_run_preserves_sources_deduplicates_and_prepares_offsets(tmp_path):
    requests = []
    pages = {
        LIST_URL: listing("/one", "/alias", "/gone", "/two", "/unused"),
        "https://hcmus.edu.vn/one": detail(),
        "https://hcmus.edu.vn/alias": detail(metadata="2026-10-27T02:00:00+07:00"),
        "https://hcmus.edu.vn/gone": httpx.Response(410),
        "https://hcmus.edu.vn/two": detail(body="Sinh viên nộp hồ sơ tốt nghiệp trước 31/10."),
    }
    run = tmp_path / "pilot"
    with client_for(pages, requests) as client:
        summary = crawl_web(
            WebCollector(client),
            run,
            limit=2,
            max_candidates=5,
            domain_holdout=True,
            group_id="pilot-template",
        )
    assert summary.status == "complete" and summary.complete
    assert summary.attempted_details == 4 and summary.accepted == 2
    assert summary.missing_reference_dates == summary.date_review_required == 2
    assert summary.outcome_counts == {"accepted": 2, "duplicate_text": 1, "http_410": 1}
    assert "https://hcmus.edu.vn/unused" not in requests
    assert requests.count("https://hcmus.edu.vn/robots.txt") == 1
    index = [CrawlIndex.model_validate(row) for row in read_jsonl(run / "index.jsonl")]
    manifest = read_jsonl(run / "raw/manifest.jsonl")
    notices = [Notice.model_validate(row) for row in read_jsonl(run / "prepared/notices.jsonl")]
    assert len(manifest) == len(notices) == len(index) == 2
    for row, source, notice in zip(index, manifest, notices, strict=True):
        raw = (run / row.raw_path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row.raw_sha256 == notice.raw_sha256
        assert raw == (run / row.snapshot_path).read_bytes()
        assert source["reference_date"] is None and source["group_id"] == "pilot-template"
        assert notice.domain_holdout and notice.privacy_review_required and not notice.synthetic
        assert notice.reference_date is None and notice.reference_date_origin == "missing"
        assert row.warnings == ["short_text"]
        for sentence in notice.sentences:
            assert 0 <= sentence.start < sentence.end <= len(notice.text)
            assert notice.text[sentence.start : sentence.end] == sentence.text
    log = [CrawlLog.model_validate(row) for row in read_jsonl(run / "crawl_log.jsonl")]
    duplicate = next(row for row in log if row.reason == "duplicate_text")
    assert duplicate.duplicate_of == index[0].doc_id
    assert (run / duplicate.snapshot_path).exists()


def test_partial_run_retains_rejected_snapshot_and_empty_prepared_file(tmp_path):
    run = tmp_path / "partial"
    pages = {LIST_URL: listing("/one"), "https://hcmus.edu.vn/one": b"<html>Login</html>"}
    with client_for(pages, []) as client:
        summary = crawl_web(WebCollector(client), run, limit=1)
    assert summary.status == "partial" and summary.accepted == 0 and not summary.complete
    assert read_jsonl(run / "prepared/notices.jsonl") == []
    log = read_jsonl(run / "crawl_log.jsonl")[-1]
    assert log["reason"] == "body_selector_mismatch"
    assert (run / log["snapshot_path"]).read_bytes() == b"<html>Login</html>"


def test_candidate_budget_is_bounded_and_zero_eligible_is_partial(tmp_path):
    for raw, expected in [
        (listing("/one", "/two"), 1),
        (listing("/one").replace("học phần".encode(), "hội thảo".encode()), 0),
    ]:
        requests = []
        with client_for({LIST_URL: raw, "https://hcmus.edu.vn/one": b"Login"}, requests) as client:
            result = crawl_web(
                WebCollector(client), tmp_path / f"budget-{expected}", limit=1, max_candidates=1
            )
        assert result.status == "partial" and result.attempted_details == expected
        assert "https://hcmus.edu.vn/two" not in requests


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(401),
        httpx.Response(403),
        httpx.Response(429),
        httpx.Response(500),
        httpx.ReadTimeout("synthetic timeout"),
        KeyboardInterrupt(),
        RuntimeError("unexpected bug"),
    ],
)
def test_fatal_errors_keep_previous_sources_and_checkpoint(tmp_path, failure):
    run = tmp_path / "failure"
    pages = {
        LIST_URL: listing("/one", "/two"),
        "https://hcmus.edu.vn/one": detail(),
        "https://hcmus.edu.vn/two": failure,
    }
    with client_for(pages, []) as client:
        with pytest.raises((httpx.HTTPError, KeyboardInterrupt, RuntimeError)):
            crawl_web(WebCollector(client), run, limit=2)
    result = CrawlSummary.model_validate_json((run / "summary.json").read_text())
    assert result.status == ("interrupted" if isinstance(failure, KeyboardInterrupt) else "failed")
    assert not result.complete and result.accepted == 1 and result.attempted_details == 2
    assert len(read_jsonl(run / "raw/manifest.jsonl")) == 1
    assert read_jsonl(run / "crawl_log.jsonl")[-1]["status"] == "failed"


def test_external_redirect_is_blocked_before_destination_robots(tmp_path):
    requests = []
    pages = {
        LIST_URL: listing("/one"),
        "https://hcmus.edu.vn/one": httpx.Response(
            302, headers={"location": "https://other.invalid/notice"}
        ),
    }
    with client_for(pages, requests) as client:
        with pytest.raises(CollectionPolicyError, match="origin"):
            crawl_web(WebCollector(client), tmp_path / "scope", limit=1)
    assert all("other.invalid" not in url for url in requests)


def test_storage_conflict_stops_run_with_downloaded_snapshot(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("Source metadata conflicts")

    monkeypatch.setattr(crawl, "save_source", fail)
    run = tmp_path / "conflict"
    with client_for(
        {LIST_URL: listing("/one"), "https://hcmus.edu.vn/one": detail()}, []
    ) as client:
        with pytest.raises(ValueError, match="conflicts"):
            crawl_web(WebCollector(client), run, limit=1)
    log = read_jsonl(run / "crawl_log.jsonl")[-1]
    assert log["status"] == "failed" and (run / log["snapshot_path"]).exists()
    assert json.loads((run / "summary.json").read_text())["accepted"] == 0


def test_output_reuse_and_invalid_options_do_not_send_http(tmp_path):
    requests = []
    run = tmp_path / "existing"
    run.mkdir()
    (run / "keep.txt").write_text("keep")
    with client_for({}, requests) as client:
        collector = WebCollector(client)
        with pytest.raises(FileExistsError):
            crawl_web(collector, run)
        for options in [{"limit": 0}, {"limit": 3, "max_candidates": 2}, {"min_chars": 0}]:
            with pytest.raises(ValueError):
                crawl_web(collector, tmp_path / "invalid", **options)
    assert requests == [] and (run / "keep.txt").read_text() == "keep"
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize(
    "run_id", ["../escape", "/absolute", "a/b", "a\\b", "CON", "LPT1", "", "a" * 65]
)
def test_invalid_run_ids(run_id):
    with pytest.raises(ValueError):
        validate_run_id(run_id)


@pytest.mark.parametrize(
    "raw, exit_code", [(detail(), None), (b"Login", 2), (httpx.Response(429), 1)]
)
def test_cli_runs_the_whole_pipeline(tmp_path, monkeypatch, capsys, raw, exit_code):
    client = client_for({LIST_URL: listing("/one"), "https://hcmus.edu.vn/one": raw}, [])
    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: client)
    args = ["crawl-web", "--run-id", "cli-pilot", "--output-root", str(tmp_path), "--limit", "1"]
    if exit_code is None:
        cli.main(args)
        assert json.loads(capsys.readouterr().out)["complete"]
        assert len(read_jsonl(tmp_path / "cli-pilot/prepared/notices.jsonl")) == 1
    else:
        with pytest.raises(SystemExit) as exc:
            cli.main(args)
        assert exc.value.code == exit_code


def test_cli_rejects_traversal_before_creating_output(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl-web", "--run-id", "../escape", "--output-root", str(tmp_path)])
    assert exc.value.code == 1 and "run-id" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_non_html_detail_is_skipped(tmp_path):
    with client_for(
        {
            LIST_URL: listing("/pdf"),
            "https://hcmus.edu.vn/pdf": httpx.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            ),
        },
        [],
    ) as client:
        result = crawl_web(WebCollector(client), tmp_path / "pdf", limit=1)
    assert result.status == "partial" and result.outcome_counts == {"non_html": 1}


def test_missing_listing_links_is_fatal_and_preserves_listing(tmp_path):
    run = tmp_path / "layout"
    with client_for({LIST_URL: b"<html>Changed layout</html>"}, []) as client:
        with pytest.raises(ValueError, match="No detail links"):
            crawl_web(WebCollector(client), run, limit=1)
    assert json.loads((run / "summary.json").read_text())["status"] == "failed"
    assert len(list((run / "snapshots").glob("*.html"))) == 1


def test_preparation_error_is_not_reported_as_success(tmp_path, monkeypatch):
    def fail(*args):
        raise ValueError("synthetic preparation error")

    monkeypatch.setattr(crawl, "prepare", fail)
    run = tmp_path / "prepare-error"
    with client_for(
        {LIST_URL: listing("/one"), "https://hcmus.edu.vn/one": detail()}, []
    ) as client:
        with pytest.raises(ValueError, match="preparation error"):
            crawl_web(WebCollector(client), run, limit=1)
    result = json.loads((run / "summary.json").read_text())
    assert result["accepted"] == 1 and result["status"] == "failed" and not result["complete"]
    assert read_jsonl(run / "crawl_log.jsonl")[-1]["kind"] == "preparation"
    assert len(read_jsonl(run / "raw/manifest.jsonl")) == 1


def test_failing_checkpoint_preserves_original_storage_error(tmp_path, monkeypatch):
    calls = []

    def fail(*args):
        calls.append(1)
        raise OSError("first failure" if len(calls) == 1 else "second failure")

    monkeypatch.setattr(crawl, "_checkpoint", fail)
    requests = []
    with client_for({}, requests) as client:
        with pytest.raises(OSError, match="first failure"):
            crawl_web(WebCollector(client), tmp_path / "disk-error", limit=1)
    assert requests == [] and len(calls) == 2


def test_multiple_publication_nodes_are_conflicting():
    raw = detail().replace(b"</article>", b"<time class='published'>27/10/2026</time></article>")
    result = parse_detail(raw)
    assert result.date_status == "conflict" and result.date_candidate is None


def test_full_task_is_kept_when_separate_paragraph_links_to_a_form():
    result = parse_detail(
        detail(
            body=(
                "<p>Sinh viên K24 nộp hồ sơ trước 30/10 tại Phòng Đào tạo.</p>"
                "<p>Biểu mẫu trong file đính kèm: <a href='form.pdf'>Tải mẫu</a></p>"
            )
        )
    )
    assert "nộp hồ sơ trước 30/10" in result.text
    assert "attachment_context_review" in result.warnings
