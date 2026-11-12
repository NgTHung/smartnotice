"""Measure model input budgets and map token windows to prepared text."""

from dataclasses import dataclass

from tokenizers import Tokenizer


@dataclass(frozen=True)
class TokenWindow:
    """One token-budgeted input window and its global prepared-text range."""

    window_id: int
    token_start: int
    token_end: int
    char_start: int
    char_end: int
    input_tokens: int


def encode(
    tokenizer: Tokenizer, text: str, *, pair: str | None = None
) -> tuple[list[int], list[tuple[int, int]]]:
    """Encode complete input without truncation or padding and return offsets."""
    result = tokenizer.encode(text, pair, add_special_tokens=True)
    return result.ids, result.offsets


def input_length(tokenizer: Tokenizer, text: str, *, pair: str | None = None) -> int:
    """Count all input tokens, including model-specific special tokens."""
    return len(tokenizer.encode(text, pair, add_special_tokens=True).ids)


def pair_input_length(tokenizer: Tokenizer, first: str, second: str) -> int:
    """Count both NLI inputs and separators as one complete model input."""
    return input_length(tokenizer, first, pair=second)


def boundary_lengths(tokenizer: Tokenizer, text: str, prefix: str, limit: int) -> dict[str, int]:
    """Measure synthetic C-1/C/C+1 inputs while preserving prefix and specials."""
    if limit < 2:
        raise ValueError("The context limit must be at least two tokens")
    lengths: dict[str, int] = {}
    for target in (limit - 1, limit, limit + 1):
        candidate = None
        for filler in ("a ", "Nộp ", "x "):
            low, high = 0, target * 4
            while low <= high:
                middle = (low + high) // 2
                count = input_length(tokenizer, prefix + filler * middle)
                if count < target:
                    low = middle + 1
                else:
                    high = middle - 1
            for chunks in (low, low - 1):
                if chunks >= 0 and input_length(tokenizer, prefix + filler * chunks) == target:
                    candidate = prefix + filler * chunks
                    break
            if candidate is not None:
                break
        if candidate is None:
            raise ValueError(f"Could not construct exact {target}-token boundary probe")
        lengths[f"C{target - limit:+d}"] = input_length(tokenizer, candidate)
    return lengths


def _body_offsets(tokenizer: Tokenizer, text: str) -> list[tuple[int, int]]:
    encoding = tokenizer.encode(text, add_special_tokens=False)
    return [offset for offset in encoding.offsets if offset[1] > offset[0]]


def head_range(
    tokenizer: Tokenizer, text: str, prefix: str, limit: int
) -> tuple[int, int, int, int]:
    """Return exact prefix-aware head input length and retained body range.

    Returns (input_tokens, char_start, char_end, body_tokens_retained). Token
    offsets are supplied by the pinned fast tokenizer and use code-point ranges.
    """
    full = tokenizer.encode(prefix + text, add_special_tokens=True)
    body_offsets = _body_offsets(tokenizer, text)
    if len(full.ids) <= limit:
        return len(full.ids), 0, len(text), len(body_offsets)
    tokenizer.enable_truncation(max_length=limit, stride=0)
    try:
        kept = tokenizer.encode(prefix + text, add_special_tokens=True)
    finally:
        tokenizer.no_truncation()
    prefix_size = len(prefix)
    ranges = [
        (max(0, start - prefix_size), min(len(text), end - prefix_size))
        for start, end in kept.offsets
        if end > prefix_size and start < prefix_size + len(text) and end > start
    ]
    end = max((stop for _, stop in ranges), default=0)
    retained = sum(1 for _, stop in body_offsets if stop <= end)
    return len(kept.ids), 0, end, retained


def make_windows(
    tokenizer: Tokenizer,
    text: str,
    prefix: str,
    limit: int,
    overlap: int,
) -> list[TokenWindow]:
    """Pack body tokens into windows, repeating prefix and counting specials.

    Each window is re-tokenized as the exact prefix plus the original text
    slice. A binary search bounds work for long notices. Every iteration must
    advance at least one body token, even when overlap exceeds window width.
    """
    if overlap < 0:
        raise ValueError("Overlap must be non-negative")
    if input_length(tokenizer, prefix) > limit:
        raise ValueError("Prefix and special tokens exceed the context limit")
    offsets = _body_offsets(tokenizer, text)
    if not offsets:
        return [TokenWindow(0, 0, 0, 0, len(text), input_length(tokenizer, prefix + text))]
    windows: list[TokenWindow] = []
    start_idx = 0
    while start_idx < len(offsets):
        if not windows:
            char_start = 0
        elif overlap == 0:
            char_start = windows[-1].char_end
        else:
            char_start = offsets[start_idx][0]
        low, high = start_idx + 1, len(offsets)
        best = start_idx
        while low <= high:
            end_idx = (low + high) // 2
            char_end = len(text) if end_idx == len(offsets) else offsets[end_idx - 1][1]
            count = input_length(tokenizer, prefix + text[char_start:char_end])
            if count <= limit:
                best = end_idx
                low = end_idx + 1
            else:
                high = end_idx - 1
        if best == start_idx:
            raise ValueError("A single body token cannot fit within the input budget")
        char_end = len(text) if best == len(offsets) else offsets[best - 1][1]
        count = input_length(tokenizer, prefix + text[char_start:char_end])
        windows.append(TokenWindow(len(windows), start_idx, best, char_start, char_end, count))
        if best == len(offsets):
            break
        start_idx = max(start_idx + 1, best - overlap)
    return windows


def interval_retention(start: int, end: int, ranges: list[tuple[int, int]]) -> str:
    """Classify whether a source span is retained by the union of ranges."""
    if start >= end:
        raise ValueError("Span start must be less than end")
    clipped = sorted((max(start, left), min(end, right)) for left, right in ranges)
    covered = 0
    cursor = start
    for left, right in clipped:
        if right <= cursor or left > cursor:
            continue
        covered += right - cursor
        cursor = right
        if cursor >= end:
            return "retained"
    if covered:
        return "partial"
    return "lost"


def covered_characters(start: int, end: int, ranges: list[tuple[int, int]]) -> int:
    """Count the union of covered code points without double-counting overlap."""
    if start > end:
        raise ValueError("Range start cannot exceed end")
    cursor = start
    covered = 0
    for left, right in sorted((max(start, left), min(end, right)) for left, right in ranges):
        if right <= cursor:
            continue
        covered += right - max(left, cursor)
        cursor = right
    return covered


def co_visible(start_end_ranges: list[tuple[int, int]], windows: list[TokenWindow]) -> bool:
    """Return whether one window contains every complete source span."""
    return any(
        all(
            window.char_start <= start and end <= window.char_end for start, end in start_end_ranges
        )
        for window in windows
    )
