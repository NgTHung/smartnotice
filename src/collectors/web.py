"""Fetch explicit URLs with robots checks and a per-origin request interval."""

import math
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "SmartNoticeCoursework/0.1"
MAX_BYTES = 5 * 1024 * 1024


class CollectionPolicyError(ValueError):
    """Stop collection when robots or redirect scope forbids a request."""


class UnsupportedContentError(ValueError):
    """Reject a successful response whose media type is not HTML."""


class WebCollector:
    """Apply robots rules before each page, including redirected destinations.

    Collection stops on unavailable robots rules except a 404 response. The
    largest of the configured interval, Crawl-delay and Request-rate spacing
    separates all requests.
    """

    def __init__(self, client: httpx.Client, interval: float = 2.0) -> None:
        """Borrow a client and require a finite request interval of at least one second."""
        if not math.isfinite(interval) or interval < 1:
            raise ValueError("The request interval must be at least one second")
        self.client = client
        self.interval = interval
        self.rules: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.delays: dict[str, float] = {}

    @staticmethod
    def origin(url: str) -> str:
        """Return a normalized HTTP(S) origin, rejecting credentials and invalid ports."""
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Use a public HTTP(S) URL without embedded credentials")
        port = parsed.port
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        suffix = (
            f":{port}"
            if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]
            else ""
        )
        return f"{parsed.scheme}://{host}{suffix}"

    def _get(self, url: str) -> httpx.Response:
        origin = self.origin(url)
        elapsed = time.monotonic() - self.last_request.get(origin, float("-inf"))
        time.sleep(max(0, self.delays.get(origin, self.interval) - elapsed))
        self.last_request[origin] = time.monotonic()
        with self.client.stream(
            "GET", url, follow_redirects=False, headers={"User-Agent": USER_AGENT}
        ) as response:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError(f"Response exceeds {MAX_BYTES} bytes: {url}")
                chunks.append(chunk)
            # iter_bytes has decoded the body; retaining compression headers decodes it twice.
            headers = response.headers.copy()
            for name in ("content-encoding", "content-length", "transfer-encoding"):
                headers.pop(name, None)
            return httpx.Response(
                response.status_code,
                headers=headers,
                content=b"".join(chunks),
                request=response.request,
            )

    def _allowed(self, url: str) -> None:
        origin = self.origin(url)
        if origin not in self.rules:
            robots_url = origin + "/robots.txt"
            response = self._get(robots_url)
            if response.status_code == 404:
                lines = ["User-agent: *", "Allow: /"]
            else:
                response.raise_for_status()
                lines = response.text.splitlines()
            parser = RobotFileParser(robots_url)
            parser.parse(lines)
            self.rules[origin] = parser
            crawl_delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0
            rate = parser.request_rate(USER_AGENT) or parser.request_rate("*")
            rate_delay = rate.seconds / rate.requests if rate and rate.requests else 0
            self.delays[origin] = max(self.interval, crawl_delay, rate_delay)
        if not self.rules[origin].can_fetch(USER_AGENT, url):
            raise CollectionPolicyError(f"robots.txt disallows collection: {url}")

    def fetch(self, url: str, *, allowed_origin: str | None = None) -> tuple[bytes, str]:
        """Return decoded HTML bytes and the URL after at most five redirects.

        When supplied, allowed_origin is checked before any request, including
        destination robots requests. Policy failures raise CollectionPolicyError;
        non-HTML responses raise UnsupportedContentError. HTTP errors propagate.
        """
        for _ in range(6):
            if allowed_origin is not None and self.origin(url) != self.origin(allowed_origin):
                raise CollectionPolicyError("Redirect or URL leaves the configured source origin")
            self._allowed(url)
            response = self._get(url)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect has no Location header")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type not in {"text/html", "application/xhtml+xml"}:
                raise UnsupportedContentError("The web collector accepts HTML pages only")
            return response.content, url
        raise ValueError("Too many redirects")
