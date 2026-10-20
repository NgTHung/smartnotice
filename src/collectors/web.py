"""Fetch explicit URLs with robots checks and a per-origin request interval."""

import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "SmartNoticeCoursework/0.1"
MAX_BYTES = 5 * 1024 * 1024


class WebCollector:
    """Apply robots rules before each page, including redirected destinations.

    Collection stops on unavailable robots rules except a 404 response. The
    larger of the configured interval and Crawl-delay separates all requests.
    """

    def __init__(self, client: httpx.Client, interval: float = 2.0):
        if interval < 1:
            raise ValueError("The request interval must be at least one second")
        self.client = client
        self.interval = interval
        self.rules: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.delays: dict[str, float] = {}

    @staticmethod
    def origin(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Use a public HTTP(S) URL without embedded credentials")
        return f"{parsed.scheme}://{parsed.netloc}"

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
            return httpx.Response(
                response.status_code,
                headers=response.headers,
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
            raise ValueError(f"robots.txt disallows collection: {url}")

    def fetch(self, url: str) -> tuple[bytes, str]:
        """Return HTML bytes and the final URL after at most five redirects."""
        for _ in range(6):
            self._allowed(url)
            response = self._get(url)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect has no Location header")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "").lower():
                raise ValueError("The web collector accepts HTML pages only")
            return response.content, url
        raise ValueError("Too many redirects")
