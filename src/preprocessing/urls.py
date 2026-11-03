"""Inspect encoded URL components consistently for privacy filtering and audit."""

import re
from dataclasses import dataclass
from urllib.parse import SplitResult, unquote, urlsplit

from smartnotice.parsers.addresses import find_email_addresses

MAX_PERCENT_DECODINGS = 8


def _decode(value: str, *, query: bool = False) -> str:
    if query:
        value = value.replace("+", " ")
    for _ in range(MAX_PERCENT_DECODINGS):
        if "%" not in value:
            return value
        if re.search(r"%(?![0-9a-fA-F]{2})", value):
            raise ValueError("invalid_url_percent_encoding")
        try:
            decoded = unquote(value, encoding="utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("invalid_url_percent_encoding") from exc
        if decoded == value:
            return value
        value = decoded
    if "%" in value:
        raise ValueError("url_percent_decoding_limit")
    return value


@dataclass(frozen=True)
class URLParameter:
    """One original query pair and its separately decoded key and value."""

    raw: str
    key: str
    value: str


@dataclass(frozen=True)
class URLInspection:
    """Decoded privacy evidence with the original parsed URL and query pairs."""

    parts: SplitResult
    query: list[URLParameter]
    outside_query: set[str]
    addresses: set[str]


def inspect_url(raw: str) -> URLInspection:
    """Inspect HTTP(S)/www URLs without changing encoded component boundaries.

    Split path segments and query pairs before percent decoding. Decode at most
    eight layers with strict UTF-8; malformed/excessive encoding raises a safe
    ValueError. Only query components interpret literal + as a space. HTML
    entities are not decoded here. No request is made.
    """
    parts = urlsplit("https://" + raw if raw.lower().startswith("www.") else raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("invalid_url")
    query = []
    for pair in parts.query.split("&") if parts.query else []:
        key, _, value = pair.partition("=")
        query.append(URLParameter(pair, _decode(key, query=True), _decode(value, query=True)))
    outside_values = [_decode(segment) for segment in parts.path.split("/")]
    outside_values.append(_decode(parts.netloc))
    if "=" in parts.fragment:
        for pair in parts.fragment.split("&"):
            key, _, value = pair.partition("=")
            outside_values.extend([_decode(key, query=True), _decode(value, query=True)])
    else:
        outside_values.append(_decode(parts.fragment))
    outside = {email.address for value in outside_values for email in find_email_addresses(value)}
    addresses = outside | {
        email.address
        for pair in query
        for value in (pair.key, pair.value)
        for email in find_email_addresses(value)
    }
    return URLInspection(parts, query, outside, addresses)
