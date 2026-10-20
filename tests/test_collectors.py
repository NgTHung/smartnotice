import httpx
import pytest
from smartnotice.collectors import web
from smartnotice.collectors.local import collect_email
from smartnotice.collectors.web import WebCollector
from smartnotice.io import read_jsonl


@pytest.fixture
def fake_clock(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(web.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(web.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    return clock


def test_robots_denial_prevents_page_request(fake_clock):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /private")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="disallows"):
            WebCollector(client).fetch("https://example.invalid/private")
    assert requests == ["https://example.invalid/robots.txt"]


def test_redirect_checks_destination_robots(fake_clock):
    requests = []

    def handler(request):
        url = str(request.url)
        requests.append(url)
        if request.url.host == "target.invalid":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(302, headers={"location": "https://target.invalid/notice"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="disallows"):
            WebCollector(client).fetch("https://source.invalid/notice")
    assert "https://target.invalid/robots.txt" in requests
    assert "https://target.invalid/notice" not in requests


def test_crawl_delay_applies_to_robots_and_page_requests(fake_clock):
    times = []

    def handler(request):
        times.append(fake_clock[0])
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\nCrawl-delay: 4")
        return httpx.Response(200, text="<p>Notice</p>", headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = WebCollector(client, interval=2)
        assert collector.fetch("https://example.invalid/one")[0] == b"<p>Notice</p>"
        collector.fetch("https://example.invalid/two")
    assert times == [100, 104, 108]


@pytest.mark.parametrize("status", [403, 429, 500, 302])
def test_unavailable_robots_fails_closed(fake_clock, status):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            WebCollector(client).fetch("https://example.invalid/notice")


def test_response_size_is_bounded(fake_clock, monkeypatch):
    monkeypatch.setattr(web, "MAX_BYTES", 40)

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"x" * 41, headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="exceeds"):
            WebCollector(client).fetch("https://example.invalid/notice")


def test_email_import_requires_consent_and_avoids_filename_metadata(tmp_path):
    path = tmp_path / "private-person-name.eml"
    path.write_bytes(b"From: person@example.invalid\n\nNotice")
    with pytest.raises(ValueError, match="consent"):
        collect_email(path, tmp_path / "raw", "", None)
    first = collect_email(path, tmp_path / "raw", "consent-001", None)
    second = collect_email(path, tmp_path / "raw", "consent-001", None)
    rows = read_jsonl(tmp_path / "raw/manifest.jsonl")
    assert len(rows) == 1
    assert first["path"] == second["path"]
    assert "private-person-name" not in str(rows)
    with pytest.raises(ValueError, match="conflicts"):
        collect_email(path, tmp_path / "raw", "different-consent", None)
