"""Reject damaged corpora and reproduce catalog text using offline HTTP only."""

import json

import httpx
import pytest
from smartnotice.collectors import web
from smartnotice.collectors.crawl import crawl_web
from smartnotice.collectors.dataset import export_catalog, fetch_catalog, validate_corpus
from smartnotice.collectors.hcmus import LIST_URL
from smartnotice.collectors.web import WebCollector
from smartnotice.io import read_jsonl, write_jsonl

ARTICLE = (
    "<meta charset='utf-8'><article><h1 class='entry-title'>Đăng ký học phần</h1>"
    "<span class='published'>06/11/2026</span><div class='entry-content'>"
    "Sinh viên K24 đăng ký học phần trước ngày 20/11/2026.</div></article>"
).encode()


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda _: None)
    listing = (
        "<div class='vc_gitem-post-data-source-post_title'>"
        "<a href='/one'>Đăng ký học phần</a></div>"
    ).encode()

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=listing if str(request.url) == LIST_URL else ARTICLE,
            headers={"content-type": "text/html"},
        )

    root = tmp_path / "corpus"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        crawl_web(WebCollector(client), root, limit=1)
    return root


def test_validate_and_export_only_source_metadata(corpus, tmp_path):
    catalog = tmp_path / "catalog"
    report = export_catalog(corpus, catalog, {"HCMUS": 1})
    assert report["validated_documents"] == 1
    assert report["human_privacy_review_complete"] is False
    rows = read_jsonl(catalog / "sources.jsonl")
    assert len(rows) == 1
    assert "text" not in rows[0] and "title" not in rows[0]


@pytest.mark.parametrize(
    "damage", ["raw", "text", "identity", "path", "review", "quota", "manifest", "summary"]
)
def test_audit_rejects_corruption(corpus, damage):
    rows = read_jsonl(corpus / "index.jsonl")
    expected = {"HCMUS": 1}
    if damage == "raw":
        (corpus / rows[0]["raw_path"]).write_bytes(b"corrupt")
    elif damage == "text":
        notices = read_jsonl(corpus / "prepared/notices.jsonl")
        notices[0]["text"] += " Changed"
        write_jsonl(corpus / "prepared/notices.jsonl", notices)
    elif damage == "identity":
        rows[0]["doc_id"] = "0" * 20
    elif damage == "path":
        rows[0]["raw_path"] = "../outside.html"
    elif damage == "review":
        rows[0]["privacy_review_required"] = False
    elif damage == "quota":
        expected = {"HCMUS": 2}
    elif damage == "manifest":
        entries = read_jsonl(corpus / "raw/manifest.jsonl")
        entries[0]["reference_date"] = "2026-11-06"
        write_jsonl(corpus / "raw/manifest.jsonl", entries)
    else:
        summary = json.loads((corpus / "summary.json").read_text())
        summary["complete"] = False
        (corpus / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    write_jsonl(corpus / "index.jsonl", rows)
    with pytest.raises(ValueError):
        validate_corpus(corpus, expected)


@pytest.mark.parametrize("changed_text", [False, True])
def test_fetch_catalog_matches_text_and_maps_changed_raw(corpus, tmp_path, changed_text):
    catalog = tmp_path / "catalog"
    export_catalog(corpus, catalog, {"HCMUS": 1})
    article = ARTICLE + b"<!-- new site layout -->"
    if changed_text:
        article = article.replace(b"20/11/2026", b"21/11/2026")

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=article, headers={"content-type": "text/html"})

    output = tmp_path / "rebuilt"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if changed_text:
            with pytest.raises(ValueError, match="Source text changed"):
                fetch_catalog(WebCollector(client), catalog / "sources.jsonl", output)
            assert not json.loads((output / "summary.json").read_text())["complete"]
        else:
            assert fetch_catalog(WebCollector(client), catalog / "sources.jsonl", output) == 1
            provenance = read_jsonl(output / "provenance.jsonl")[0]
            assert not provenance["raw_hash_matches_catalog"]
            assert provenance["doc_id"] != provenance["catalog_doc_id"]
            assert read_jsonl(output / "prepared/notices.jsonl")[0]["privacy_review_required"]


def test_fetch_rejects_external_url_before_io(corpus, tmp_path):
    catalog = tmp_path / "catalog"
    export_catalog(corpus, catalog, {"HCMUS": 1})
    rows = read_jsonl(catalog / "sources.jsonl")
    rows[0]["url"] = "https://outside.invalid/one"
    write_jsonl(catalog / "sources.jsonl", rows)
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP"))) as c:
        with pytest.raises(ValueError, match="configured source"):
            fetch_catalog(WebCollector(c), catalog / "sources.jsonl", tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()
