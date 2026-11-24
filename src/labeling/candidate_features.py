"""Encode inference-time candidate and context features as a sparse matrix."""

from numpy import float32
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from smartnotice.labeling.candidate_generation import LABELS
from smartnotice.preprocessing.dates import normalize_date
from smartnotice.preprocessing.links import WEB_LINK
from smartnotice.schemas import Notice, SpanCandidate

CONTEXT_CHARS = 100
_CUES = ("trước ngày", "sinh viên", "không cần", "đã", "chưa", "trừ", "nếu")


def _mask_urls(text):
    return WEB_LINK.sub(" <url> ", text)


def candidate_feature_row(notice: Notice, candidate: SpanCandidate) -> dict:
    """Extract fields available at prediction time without IDs or annotation evidence."""
    text = notice.text
    start, end = candidate.start, candidate.end
    left = text[max(0, start - CONTEXT_CHARS) : start]
    right = text[end : end + CONTEXT_CHARS]
    surface = candidate.text
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    sentence = next((s for s in notice.sentences if s.start <= start < s.end), None)
    structured = {
        "chars": len(surface),
        "whitespace_units": len(surface.split()),
        "digit_share": sum(char.isdigit() for char in surface) / len(surface),
        "numeric_date": float(normalize_date(surface, notice.reference_date)[0] is not None),
        "has_url": float(WEB_LINK.search(surface) is not None),
        "document_position": start / len(text),
        "line_position": (start - line_start) / (line_end - line_start),
    }
    if sentence is not None:
        structured["sentence_position"] = (start - sentence.start) / (sentence.end - sentence.start)
    for cue in _CUES:
        structured["cue:" + cue] = float(cue in (left + surface + right).casefold())
    return {
        "surface": _mask_urls(surface),
        "context": _mask_urls(left) + " <span> " + _mask_urls(right),
        "label": candidate.proposed_label,
        "structured": structured,
        "rules": {f"rule:{rule}": 1 for rule in candidate.rule_ids},
    }


class CandidateFeatures:
    """Fit candidate and context TF-IDF and optional structure on training rows."""

    def __init__(self, *, context: bool = True, structured: bool = True, rules: bool = True):
        self.context = context
        self.structured = structured
        self.rules = rules
        settings = {"analyzer": "char", "ngram_range": (2, 4), "max_features": 6000}
        self.surface_vectorizer = TfidfVectorizer(**settings, dtype=float32)
        self.context_vectorizer = TfidfVectorizer(**settings, dtype=float32)
        self.feature_vectorizer = DictVectorizer()

    def _attributes(self, row):
        attributes = {"label": row["label"]}
        if self.structured:
            attributes.update(row["structured"])
        if self.rules:
            attributes.update(row["rules"])
        return attributes

    def fit(self, rows: list[dict]) -> "CandidateFeatures":
        """Fit vocabularies on a nonempty training set and return this encoder."""
        self.surface_vectorizer.fit(" " + row["surface"] + " " for row in rows)
        if self.context:
            self.context_vectorizer.fit(row["context"] for row in rows)
        self.feature_vectorizer.fit(self._attributes(row) for row in rows)
        return self

    def transform(self, rows: list[dict]) -> csr_matrix:
        """Return CSR features with shared and label-specific text blocks."""
        surface = self.surface_vectorizer.transform(" " + row["surface"] + " " for row in rows)
        blocks = [surface]
        if self.context:
            blocks.append(self.context_vectorizer.transform(row["context"] for row in rows))
        text = hstack(blocks, format="csr")
        for label in LABELS:
            mask = [[row["label"] == label] for row in rows]
            blocks.append(text.multiply(mask))
        blocks.append(self.feature_vectorizer.transform(self._attributes(row) for row in rows))
        return hstack(blocks, format="csr", dtype=float32)
