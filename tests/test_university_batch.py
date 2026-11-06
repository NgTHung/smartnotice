"""Verify complete, insufficient and cross-institution duplicate batch outcomes."""

import json
import runpy
import sys
from pathlib import Path

import httpx
import pytest
from smartnotice.collectors import web
from smartnotice.collectors.sources import SOURCES


@pytest.mark.parametrize("case", ["complete", "short_source", "duplicate_across_sources"])
def test_batch_requires_exact_quotas_and_distinct_text(tmp_path, monkeypatch, case):
    original_client = httpx.Client
    monkeypatch.setattr(web.time, "sleep", lambda _: None)
    targets = {"hcmus-student": 40, "uit-student": 30, "ueh-student": 30}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        source = next(
            source
            for source in targets
            if request.url.host == httpx.URL(SOURCES[source].listing_url).host
        )
        adapter = SOURCES[source]
        if str(request.url) == adapter.listing_url:
            count = targets[source] - int(case == "short_source" and source == "ueh-student")
            anchors = "".join(
                f'<h3><a href="/bai-viet/{i}">Đăng ký học phần</a></h3>' for i in range(count)
            )
            raw = f'<div id="content" class="vc_gitem-post-data-source-post_title">{anchors}</div>'
        else:
            i = request.url.path.rsplit("/", 1)[-1]
            name = (
                "UIT"
                if (case == "duplicate_across_sources" and source == "ueh-student" and i == "0")
                else adapter.institution
            )
            raw = (
                "<meta charset='utf-8'><article>"
                "<h1 id='page-title' class='entry-title page-title'>Đăng ký học phần</h1>"
                "<span class='published'>06/11/2026</span>"
                "<div class='entry-content field-name-body bs-desc'>"
                f"Sinh viên {name} đăng ký học phần đợt {i} trước ngày 20/11/2026."
                "</div></article>"
            )
        return httpx.Response(200, text=raw, headers={"content-type": "text/html; charset=utf-8"})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(
        sys, "argv", ["crawl_universities.py", "--run-id", "batch", "--output-root", str(tmp_path)]
    )
    script = Path(__file__).resolve().parents[1] / "tools/crawl_universities.py"
    main = runpy.run_path(str(script))["main"]
    code = main()
    summary = json.loads((tmp_path / "batch/summary.json").read_text(encoding="utf-8"))
    assert (code == 0) == (case == "complete")
    assert summary["complete"] == (case == "complete")
    if case == "complete":
        assert summary["institutions"] == {"HCMUS": 40, "UIT": 30, "UEH": 30}
        assert (tmp_path / "batch/validation.json").exists()
    else:
        assert summary["accepted"] == 99
