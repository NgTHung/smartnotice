"""Read the HCMUS student listing without inferring verified dates or labels."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from smartnotice.collectors.web import WebCollector
from smartnotice.parsers.html import parse_html
from smartnotice.schemas import CrawlCandidate

LIST_URL = "https://hcmus.edu.vn/thong-tin-danh-cho-nguoi-hoc/"
LINK_SELECTOR = ".vc_gitem-post-data-source-post_title a[href]"
BODY_SELECTOR = "article .entry-content"
TITLE_SELECTOR = "article .entry-title"
DATE_SELECTOR = "article .published"
_ACADEMIC_TERMS = (
    "học phần",
    "học phí",
    "học bổng",
    "tốt nghiệp",
    "học tập",
    "học vụ",
    "bảo lưu",
    "chuyển ngành",
    "nhập học",
    "ngành học",
    "sinh hoạt công dân",
    "rèn luyện",
    "chứng chỉ",
    "văn bằng",
    "miễn giảm",
    "xác nhận",
    "bảo hiểm",
    "thực tập",
    "học lại",
    "thi lại",
    "phúc khảo",
    "thời khóa biểu",
    "nghỉ học",
    "giáo dục quốc phòng",
    "anh văn",
    "ngoại ngữ",
)
_EXCLUDED_TERMS = ("danh sách", "kết quả", "chúc mừng", "thư mời")
_POLICY_PREFIXES = (
    "quy chế",
    "quy định",
    "ban hành quy chế",
    "ban hành quy định",
    "quyết định",
    "cảnh báo",
    "thông tin giải đáp",
)
_ACTIONS = (
    "đăng ký",
    "nộp",
    "hoàn thành",
    "điều chỉnh",
    "bổ sung",
    "xác nhận",
    "cập nhật thông tin",
    "thực hiện",
    "đề nghị",
    "khảo sát",
    "tham gia",
    "đóng học phí",
    "đóng phí",
    "thanh toán",
    "kiểm tra",
    "phản hồi",
    "khiếu nại",
    "tham dự",
    "nghỉ học",
    "tiếp nhận",
)
_ATTACHMENT_HANDOFFS = (
    "file đính kèm",
    "tệp đính kèm",
    "tập tin đính kèm",
    "tài liệu đính kèm",
    "file sau",
    "link sau",
    "xem chi tiết tài liệu",
    "trong 2 file",
)


class NoticeRejected(ValueError):
    """Reject a downloaded page using a stable reason code for the collection log."""

    def __init__(self, reason: str) -> None:
        """Expose a rejection reason for the caller's persisted collection log."""
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class HcmusDetail:
    """Carry extracted text and unverified publication evidence from one detail page."""

    title: str
    text: str
    date_candidate: date | None
    date_display: str | None
    date_metadata: str | None
    date_status: str
    warnings: tuple[str, ...]


def selection_reason(title: str) -> str:
    """Return eligible for academic titles, or an explicit exclusion reason.

    This substring heuristic defines sampling, not annotation or content quality.
    Every accepted notice still requires human content review.
    """
    title = unicodedata.normalize("NFC", title).casefold()
    if any(term in title for term in _EXCLUDED_TERMS) or title.startswith(_POLICY_PREFIXES):
        return "excluded_title"
    if not any(term in title for term in _ACADEMIC_TERMS):
        return "outside_academic_scope"
    return "eligible"


def discover_links(
    raw: bytes, base_url: str, *, link_selector: str = LINK_SELECTOR
) -> list[CrawlCandidate]:
    """Return unique same-origin links in DOM order, preserving identifying queries.

    Remove fragments and normalize default ports. Ignore credentialed, non-HTTP,
    off-origin, empty-title and obvious attachment links. An empty result raises
    ValueError so a changed selector cannot look like a successful empty crawl.
    """
    soup = BeautifulSoup(raw, "html.parser")
    origin = WebCollector.origin(base_url)
    found: dict[str, CrawlCandidate] = {}
    for anchor in soup.select(link_selector):
        try:
            url = urldefrag(urljoin(base_url, anchor["href"].strip()))[0]
            if WebCollector.origin(url) != origin:
                continue
        except ValueError:
            continue
        target = urlsplit(url)
        if re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?)$", target.path, re.I):
            continue
        url = urlunsplit((*urlsplit(origin)[:2], target.path or "/", target.query, ""))
        title = unicodedata.normalize("NFC", anchor.get_text(" ", strip=True))
        if title and url != base_url and url not in found:
            found[url] = CrawlCandidate(
                url=url, title=title, selection_reason=selection_reason(title)
            )
    if not found:
        raise ValueError("No detail links found; inspect the configured listing selector")
    return list(found.values())


def _publication_date(
    soup: BeautifulSoup, date_selector: str = DATE_SELECTOR
) -> tuple[date | None, str | None, str | None, str]:
    nodes = soup.select(date_selector)
    display = nodes[0].get_text(" ", strip=True) if nodes else None
    metadata = soup.select('meta[property="article:published_time"]')
    timestamp = metadata[0].get("content") if metadata else None
    if len(nodes) > 1 or len(metadata) > 1:
        return None, display, timestamp, "conflict"
    if not display:
        return None, display, timestamp, "missing"
    try:
        match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", display)
        candidate = datetime.strptime(
            match[0] if match and date_selector != DATE_SELECTOR else display, "%d/%m/%Y"
        ).date()
    except ValueError:
        return None, display, timestamp, "invalid"
    if timestamp:
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone(timedelta(hours=7)))
        except (ValueError, OverflowError):
            return candidate, display, timestamp, "invalid"
        if parsed.date() != candidate:
            return candidate, display, timestamp, "conflict"
    return candidate, display, timestamp, "unverified"


def parse_detail(
    raw: bytes,
    *,
    body_selector: str = BODY_SELECTOR,
    title_selector: str = TITLE_SELECTOR,
    date_selector: str = DATE_SELECTOR,
) -> HcmusDetail:
    """Extract exactly one title/body and retain date evidence without verification.

    Reject missing or ambiguous selectors, titles outside the sampling scope and
    pages with no action-bearing prose outside attachments. Missing/conflicting
    publication dates remain reviewable. No collection date becomes a reference.
    """
    soup = BeautifulSoup(raw, "html.parser")
    bodies, titles = soup.select(body_selector), soup.select(title_selector)
    if len(bodies) != 1:
        raise NoticeRejected("body_selector_mismatch")
    if len(titles) != 1 or not titles[0].get_text(" ", strip=True):
        raise NoticeRejected("title_selector_mismatch")
    title = titles[0].get_text(" ", strip=True)
    reason = selection_reason(title)
    if reason != "eligible":
        raise NoticeRejected(reason)
    for table in bodies[0].select("table"):
        table_text = unicodedata.normalize("NFC", table.get_text(" ", strip=True)).casefold()
        has_names = re.search(r"\bhọ(?: và)? tên\b", table_text)
        has_ids = re.search(r"\b(?:mssv|mshv|mã\s*(?:sv|hv|sinh viên|học viên))\b", table_text)
        identifiers = re.findall(r"(?<!\w)\d{6,10}(?:x{1,4})?(?!\w)", table_text)
        if has_names and has_ids and len(identifiers) >= 2:
            raise NoticeRejected("personal_roster")
    prose = BeautifulSoup(str(bodies[0]), "html.parser")
    for tag in prose.select("a, img, iframe, object, embed, script, style, noscript, .post-views"):
        tag.decompose()
    prose_text = unicodedata.normalize("NFC", parse_html(str(prose))).casefold()
    if "nhiệm vụ của các đơn vị" in prose_text:
        raise NoticeRejected("staff_administration")
    has_attachment_handoff = any(handoff in prose_text for handoff in _ATTACHMENT_HANDOFFS)
    segments = re.split(r"\n+|(?<=[.!?;])\s+", prose_text)
    prose_text = " ".join(
        segment
        for segment in segments
        if not any(handoff in segment for handoff in _ATTACHMENT_HANDOFFS)
        or re.search(
            r"(?:trước|chậm nhất|hạn(?: cuối| chót)?|từ|đến)[^.!?\n]{0,30}\b\d{1,2}[/.-]\d{1,2}",
            segment,
        )
    )
    if not prose_text or not any(
        re.search(r"(?<!\w)" + re.escape(action) + r"(?!\w)", prose_text) for action in _ACTIONS
    ):
        raise NoticeRejected("attachment_only_or_no_action_prose")
    text = parse_html(raw, body_selector)
    if not text.strip():
        raise NoticeRejected("empty_body")
    candidate, display, timestamp, status = _publication_date(soup, date_selector)
    warnings = []
    if has_attachment_handoff:
        warnings.append("attachment_context_review")
    if "\ufffd" in text:
        warnings.append("replacement_character")
    if bodies[0].select("td[rowspan], td[colspan], th[rowspan], th[colspan]"):
        warnings.append("merged_table_cells")
    return HcmusDetail(title, text, candidate, display, timestamp, status, tuple(warnings))
