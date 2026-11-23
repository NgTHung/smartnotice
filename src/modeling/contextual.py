"""Extract typed spans and their relations from local token and document context."""

import hashlib
import re
from bisect import bisect_right
from collections.abc import Iterator
from difflib import SequenceMatcher

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.pipeline import make_pipeline
from smartnotice.modeling.data import SPAN_LABELS, Document, SpanKey, labeled_links, span_key
from smartnotice.modeling.extraction import pair_keys
from smartnotice.schemas import Notice

TOKEN = re.compile(r"\w+|[^\w\s]")


def _word(raw):
    return re.sub(r"\d", "0", raw.casefold())


def _sentences(notice):
    for sentence in notice.sentences:
        tokens = list(TOKEN.finditer(notice.text, sentence.start, sentence.end))
        words = [_word(t.group()) for t in tokens]
        features = []
        for i, token in enumerate(tokens):
            context = [words[j] if 0 <= j < len(words) else "<edge>" for j in range(i - 2, i + 3)]
            features.append(
                {
                    **{f"w{j - 2}": w for j, w in enumerate(context)},
                    **{
                        f"p{j}": a + "|" + b
                        for j, (a, b) in enumerate(zip(context, context[1:], strict=False))
                    },
                    "upper": token.group().isupper(),
                    "capital": token.group()[0].isupper(),
                    "source": notice.source_type,
                    "first": i == 0,
                    "last": i + 1 == len(tokens),
                }
            )
        if tokens:
            yield tokens, features


def _tags(tokens, spans):
    starts = {t.start(): i for i, t in enumerate(tokens)}
    ends = {t.end(): i for i, t in enumerate(tokens)}
    labels = {label: ["O"] * len(tokens) for label in SPAN_LABELS[1:]}
    for a, b, label in sorted(spans, key=lambda s: (s[0], -s[1])):
        if a not in starts or b not in ends:
            continue
        first, last = starts[a], ends[b]
        tags = labels[label]
        if all(t == "O" for t in tags[first : last + 1]):
            tags[first : last + 1] = ["B"] + ["I"] * (last - first)
    return labels


def _intervals(tokens, tags, label):
    start = None
    for i, tag in enumerate(tags):
        if start is not None and tag != "I":
            yield tokens[start].start(), tokens[i - 1].end(), label
            start = None
        if tag != "O" and start is None:
            start = i
    if start is not None:
        yield tokens[start].start(), tokens[-1].end(), label


def _pairs(notice, spans):
    starts = [s.start for s in notice.sentences]
    positions = {s: bisect_right(starts, s[0]) - 1 for s in spans}
    actions = sorted(s for s in spans if s[2] == "ACTION")
    action_starts = [s[0] for s in actions]
    for action, argument in pair_keys(spans):
        a, b = action[0], argument[0]
        sid = positions[argument]
        delta = positions[action] - sid
        prefix = TOKEN.findall(notice.text[notice.sentences[sid].start : b])[-4:]
        phrase = TOKEN.findall(notice.text[b : argument[1]])[:4]
        between = abs(bisect_right(action_starts, a) - bisect_right(action_starts, b))
        yield (
            (action, argument),
            {
                "type": argument[2],
                "sent_delta": str(max(-6, min(6, delta))),
                "direction": str(a <= b),
                "actions_between": str(min(4, between)),
                "distance": str(min(12, abs(a - b).bit_length())),
                "first_action": action == actions[0],
                "last_action": action == actions[-1],
                "arg_first_sentence": sid == 0,
                "source": notice.source_type,
                **{f"before{-i}": _word(t) for i, t in enumerate(reversed(prefix), 1)},
                **{f"arg{i}": _word(t) for i, t in enumerate(phrase)},
            },
        )


class ContextExtractor:
    """Fit independent BIO taggers per span type and one link classifier per argument type."""

    def __init__(self, seed: int):
        self.seed = seed
        self.vectorizer = DictVectorizer()
        self.taggers = {}
        self.linkers = {}

    def fit(self, documents: list[Document]) -> None:
        """Learn token features, BIO tags, and relation scores from labeled training notices."""
        features = []
        targets = {label: [] for label in SPAN_LABELS[1:]}
        pairs = {label: ([], []) for label in SPAN_LABELS[2:]}
        for doc in documents:
            spans = {span_key(s) for s in doc.annotation.spans}
            for tokens, rows in _sentences(doc.notice):
                features.extend(rows)
                for label, tags in _tags(tokens, spans).items():
                    targets[label].extend(tags)
            links = {(a, b): role for a, b, role in labeled_links(doc.annotation)}
            for pair, row in _pairs(doc.notice, spans):
                xs, ys = pairs[pair[1][2]]
                xs.append(row)
                ys.append(links.get(pair, "NO_RELATION"))
        matrix = self.vectorizer.fit_transform(features)
        for label, tags in targets.items():
            model = SGDClassifier(
                loss="log_loss", alpha=0.00002, max_iter=80, tol=0.0001, random_state=self.seed
            )
            if len(set(tags)) > 1:
                self.taggers[label] = model.fit(matrix, tags)
        for label, (xs, ys) in pairs.items():
            if len(set(ys)) > 1:
                self.linkers[label] = make_pipeline(
                    DictVectorizer(), LogisticRegression(C=2, max_iter=300)
                ).fit(xs, ys)
            elif ys:
                self.linkers[label] = ys[0]

    def spans(self, notice: Notice) -> set[SpanKey]:
        """Predict typed character intervals using only source sentences and source type."""
        result = set()
        for tokens, features in _sentences(notice):
            matrix = self.vectorizer.transform(features)
            for label, model in self.taggers.items():
                result.update(_intervals(tokens, model.predict(matrix), label))
        return result

    def links(self, notice: Notice, spans: set[SpanKey]) -> Iterator[tuple]:
        """Yield the best positive role and its probability per candidate endpoint pair."""
        groups = {label: [] for label in self.linkers}
        for pair, row in _pairs(notice, spans):
            if pair[1][2] in groups:
                groups[pair[1][2]].append((pair, row))
        for label, rows in groups.items():
            if not rows:
                continue
            model = self.linkers[label]
            if isinstance(model, str):
                if model != "NO_RELATION":
                    for pair, _ in rows:
                        yield (*pair, model), 1.0
                continue
            positive = np.flatnonzero(model.classes_ != "NO_RELATION")
            probs = model.predict_proba([row for _, row in rows])[:, positive]
            for (pair, _), scores in zip(rows, probs, strict=True):
                i = scores.argmax()
                yield (*pair, str(model.classes_[positive[i]])), float(scores[i])


def _fingerprints(tokens):
    return [hashlib.blake2b(_word(t.group()).encode(), digest_size=12).digest() for t in tokens]


class TemplateExtractor:
    """Transfer aligned span boundaries from similar training sentences onto new notices."""

    def __init__(self, fallback: ContextExtractor, similarity: float):
        self.fallback = fallback
        self.similarity = similarity
        self.vectorizer = HashingVectorizer(
            analyzer="char",
            ngram_range=(3, 5),
            n_features=2**19,
            alternate_sign=False,
            dtype=np.float32,
        )

    def fit(self, documents: list[Document]) -> None:
        """Index training sentences, storing token fingerprints and within-sentence span bounds."""
        texts, self.templates = [], []
        for doc in documents:
            notice = doc.notice
            for sent in notice.sentences:
                tokens = list(TOKEN.finditer(notice.text, sent.start, sent.end))
                if not tokens:
                    continue
                starts = {t.start(): i for i, t in enumerate(tokens)}
                ends = {t.end(): i for i, t in enumerate(tokens)}
                spans = {
                    (starts[s.start], ends[s.end], s.label)
                    for s in doc.annotation.spans
                    if s.start in starts and s.end in ends
                }
                texts.append(_word(sent.text))
                self.templates.append((_fingerprints(tokens), sorted(spans)))
        self.index = self.vectorizer.transform(texts).T.tocsr()

    def spans(self, notice: Notice) -> set[SpanKey]:
        """Use aligned interval endpoints above the similarity cutoff and BIO spans elsewhere."""
        fallback = self.fallback.spans(notice)
        result = set()
        scores = (
            self.vectorizer.transform([_word(s.text) for s in notice.sentences]) @ self.index
        ).tocsr()
        for i, sent in enumerate(notice.sentences):
            row = scores.getrow(i)
            if not row.nnz or row.data.max() < self.similarity:
                result.update(s for s in fallback if sent.start <= s[0] and s[1] <= sent.end)
                continue
            index = row.indices[row.data.argmax()]
            source, intervals = self.templates[index]
            tokens = list(TOKEN.finditer(notice.text, sent.start, sent.end))
            dest = _fingerprints(tokens)
            alignment = {}
            for a, b, length in SequenceMatcher(
                None, source, dest, autojunk=False
            ).get_matching_blocks():
                alignment.update((a + k, b + k) for k in range(length))
            for a, b, label in intervals:
                if a in alignment and b in alignment:
                    result.add((tokens[alignment[a]].start(), tokens[alignment[b]].end(), label))
        return result

    def links(self, notice: Notice, spans: set[SpanKey]) -> Iterator[tuple]:
        """Score transferred or fallback endpoints using the fitted contextual link classifiers."""
        return self.fallback.links(notice, spans)


class DocumentTemplateExtractor:
    """Transfer event structure when a notice shares aligned passages with a training notice."""

    def __init__(self, fallback: TemplateExtractor, similarity: float):
        self.fallback = fallback
        self.similarity = similarity

    def fit(self, documents: list[Document]) -> None:
        """Index training notices by hashed character features, token offsets, and labeled links."""
        self.records = []
        texts = []
        for doc in documents:
            tokens = list(TOKEN.finditer(doc.notice.text))
            starts = {t.start(): i for i, t in enumerate(tokens)}
            ends = {t.end(): i for i, t in enumerate(tokens)}
            spans = {
                span_key(s): (starts[s.start], ends[s.end])
                for s in doc.annotation.spans
                if s.start in starts and s.end in ends
            }
            self.records.append((_fingerprints(tokens), spans, labeled_links(doc.annotation)))
            texts.append(_word(doc.notice.text))
        self.index = self.fallback.vectorizer.transform(texts).T.tocsr()

    def candidates(self, notice: Notice) -> tuple[set[SpanKey], list]:
        """Return exact typed spans and scored links using only the supplied notice at inference."""
        spans = self.fallback.spans(notice)
        scores = (self.fallback.vectorizer.transform([_word(notice.text)]) @ self.index).tocsr()
        if not scores.nnz or scores.data.max() < self.similarity:
            return spans, list(self.fallback.links(notice, spans))
        source, labeled, relations = self.records[scores.indices[scores.data.argmax()]]
        tokens = list(TOKEN.finditer(notice.text))
        mapping = {}
        covered = []
        for a, b, n in SequenceMatcher(
            None, source, _fingerprints(tokens), autojunk=False
        ).get_matching_blocks():
            mapping.update((a + k, b + k) for k in range(n))
            if n >= 6:
                covered.append((tokens[b].start(), tokens[b + n - 1].end()))
        projected = {}
        for key, (a, b) in labeled.items():
            if (
                a in mapping
                and b in mapping
                and abs((mapping[b] - mapping[a]) - (b - a)) <= max(2, (b - a) // 3)
            ):
                projected[key] = (tokens[mapping[a]].start(), tokens[mapping[b]].end(), key[2])
        valid = {(s.start, s.end) for s in notice.sentences}
        projected = {
            k: v for k, v in projected.items() if any(a <= v[0] and v[1] <= b for a, b in valid)
        }
        transferred = set(projected.values())
        spans = transferred | {
            s for s in spans if not any(a <= s[0] and s[1] <= b for a, b in covered)
        }
        links = [
            (key, score)
            for key, score in self.fallback.links(notice, spans)
            if key[0] not in transferred or key[1] not in transferred
        ]
        links.extend(
            ((projected[a], projected[b], role), 1.0)
            for a, b, role in relations
            if a in projected and b in projected
        )
        return spans, links
