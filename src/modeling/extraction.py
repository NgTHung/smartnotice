"""Score candidate spans and directed action–argument links with one BamiBERT encoder."""

import random
from collections import defaultdict
from itertools import product

import torch
from smartnotice.labeling.validation import validate_annotation
from smartnotice.modeling.data import (
    LINK_LABELS,
    SPAN_LABELS,
    LinkKey,
    Location,
    SpanKey,
    TokenDocument,
    labeled_links,
    span_key,
)
from smartnotice.preprocessing.dates import normalize_date
from smartnotice.schemas import Annotation, Argument, Event, Notice, Span
from torch import nn
from torch.nn import functional as F

SPAN_IDS = {label: i for i, label in enumerate(SPAN_LABELS)}
LINK_IDS = {label: i for i, label in enumerate(LINK_LABELS)}
type Bounds = tuple[int, int]


def sample_negatives(positives: list, negatives: list, rng: random.Random) -> list:
    """Keep all positives and up to five negatives each, with a 32-negative floor."""
    return positives + rng.sample(negatives, min(len(negatives), max(32, len(positives) * 5)))


def pair_keys(spans: set[SpanKey]) -> list[tuple[SpanKey, SpanKey]]:
    """Enumerate every directed ACTION-to-argument pair within a document."""
    actions = sorted(s for s in spans if s[2] == "ACTION")
    arguments = sorted(s for s in spans if s[2] != "ACTION")
    return list(product(actions, arguments))


def keep_nonoverlapping(ranked: list[tuple[float, SpanKey]]) -> list[tuple[float, SpanKey]]:
    """Keep the highest-scored span among overlapping candidates of the same type."""
    kept = []
    by_type = defaultdict(list)
    for score, (start, end, label) in sorted(ranked, key=lambda item: (-item[0], item[1])):
        if any(start < right and left < end for left, right in by_type[label]):
            continue
        by_type[label].append((start, end))
        kept.append((score, (start, end, label)))
    return kept


class Extractor(nn.Module):
    """Predict exact typed spans and masked relation classes for a document."""

    def __init__(self, encoder: nn.Module, max_width: int, pad_id: int):
        super().__init__()
        self.encoder = encoder
        self.pad_id = pad_id
        self.width = nn.Embedding(max_width + 1, 32)
        self.span_embedding = nn.Sequential(
            nn.Linear(encoder.config.hidden_size * 3 + 32, 192),
            nn.GELU(),
            nn.Dropout(0.1),
        )
        self.span_head = nn.Linear(192, len(SPAN_LABELS) - 1)
        self.link_head = nn.Sequential(
            nn.Linear(384 + len(SPAN_LABELS) + 3, 192),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(192, len(LINK_LABELS)),
        )

    def encode(self, doc: TokenDocument, micro_batch: int = 4) -> torch.Tensor:
        """Encode every window separately and pad the hidden states to one shape."""
        dev = self.width.weight.device
        length = max(map(len, doc.windows))
        windows = []
        for start in range(0, len(doc.windows), micro_batch):
            batch = doc.windows[start : start + micro_batch]
            ids = torch.tensor([v + [self.pad_id] * (length - len(v)) for v in batch], device=dev)
            mask = (
                torch.arange(length, device=dev)
                < torch.tensor(list(map(len, batch)), device=dev)[:, None]
            )
            windows.append(self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state)
        return torch.cat(windows)

    def represent(self, hidden: torch.Tensor, locations: list[Location]) -> torch.Tensor:
        """Pool inclusive token endpoints and means, then project to span vectors."""
        dev = hidden.device
        window, first, last = torch.tensor(
            [(s.window, s.first, s.last) for s in locations], device=dev
        ).T
        cumulative = F.pad(hidden.float().cumsum(dim=1), (0, 0, 1, 0))
        width = last - first + 1
        mean = (cumulative[window, last + 1] - cumulative[window, first]) / width[:, None]
        return self.span_embedding(
            torch.cat(
                [
                    hidden[window, first],
                    hidden[window, last],
                    mean,
                    self.width(width),
                ],
                dim=-1,
            )
        )

    def relations(
        self,
        doc: TokenDocument,
        hidden: torch.Tensor,
        pairs: list[tuple[SpanKey, SpanKey]],
    ) -> torch.Tensor:
        """Score pairs using endpoint vectors, distance, and relation type masks."""
        spans = sorted({s for pair in pairs for s in pair})
        vectors = self.represent(hidden, [doc.candidates[s[:2]] for s in spans])
        indices = {s: i for i, s in enumerate(spans)}
        dev = hidden.device
        a, b = torch.tensor([(indices[a], indices[b]) for a, b in pairs], device=dev).T
        types = torch.tensor([SPAN_IDS[s[2]] for _, s in pairs], device=dev)
        sentence_ends = torch.tensor([s.end for s in doc.document.notice.sentences], device=dev)
        first_positions = torch.tensor([(a[0], b[0]) for a, b in pairs], device=dev)
        sentence = torch.searchsorted(sentence_ends, first_positions, right=True)
        distance = (first_positions[:, 1] - first_positions[:, 0]).float()
        features = torch.stack(
            [
                distance.sign() * distance.abs().log1p() / 10,
                (sentence[:, 0] == sentence[:, 1]).float(),
                torch.tensor(
                    [
                        doc.candidates[a[:2]].window != doc.candidates[b[:2]].window
                        for a, b in pairs
                    ],
                    device=dev,
                ).float(),
            ],
            dim=-1,
        )
        logits = self.link_head(
            torch.cat(
                [
                    vectors[a],
                    vectors[b],
                    F.one_hot(types, len(SPAN_LABELS)),
                    features,
                ],
                dim=-1,
            )
        )
        allowed = torch.zeros_like(logits, dtype=torch.bool)
        allowed[:, 0] = True
        allowed[types == SPAN_IDS["TIME"], 1:4] = True
        for label in SPAN_LABELS[3:]:
            allowed[types == SPAN_IDS[label], LINK_IDS[label]] = True
        return logits.masked_fill(~allowed, -torch.inf)

    def loss(
        self,
        doc: TokenDocument,
        rng: random.Random,
        joint: bool,
        positive_weight: float,
    ) -> torch.Tensor:
        """Compute weighted span loss and optional supervised link loss."""
        hidden = self.encode(doc)
        gold = defaultdict(set)
        for span in doc.document.annotation.spans:
            gold[span.start, span.end].add(span.label)
        positives = [key for key in gold if key in doc.candidates]
        negatives = [key for key in doc.candidates if key not in gold]
        near = [
            key
            for key in negatives
            if any(key[0] == span[0] or key[1] == span[1] for span in positives)
        ]
        near = rng.sample(near, min(len(near), max(len(positives) * 2, 8)))
        near_set = set(near)
        sampled = (
            sample_negatives(positives, [key for key in negatives if key not in near_set], rng)
            + near
        )
        if not sampled:
            raise ValueError(f"No trainable span candidates: {doc.document.notice.doc_id}")
        target = torch.tensor(
            [[label in gold.get(key, ()) for label in SPAN_LABELS[1:]] for key in sampled],
            device=hidden.device,
            dtype=torch.float,
        )
        vectors = self.represent(hidden, [doc.candidates[key] for key in sampled])
        loss = F.binary_cross_entropy_with_logits(
            self.span_head(vectors),
            target,
            pos_weight=target.new_full((len(SPAN_LABELS) - 1,), positive_weight),
        )
        if joint:
            span_set = {(*key, label) for key in positives for label in gold[key]}
            links = {(a, b): label for a, b, label in labeled_links(doc.document.annotation)}
            pairs = pair_keys(span_set)
            selected = sample_negatives(
                [p for p in pairs if p in links], [p for p in pairs if p not in links], rng
            )
            if selected:
                logits = self.relations(doc, hidden, selected)
                labels = torch.tensor(
                    [LINK_IDS[links.get(pair, "NO_RELATION")] for pair in selected],
                    device=hidden.device,
                )
                loss = loss + F.cross_entropy(logits, labels)
        return loss

    @torch.no_grad()
    def predict(
        self,
        doc: TokenDocument,
        thresholds: tuple[float, ...],
        limit: int,
        *,
        suppress_same_type_overlap: bool = False,
    ) -> tuple[dict[float, set[SpanKey]], dict[LinkKey, float]]:
        """Score windowed spans once and link the union of retained candidate spans."""
        hidden = self.encode(doc)
        keys = list(doc.candidates)
        scores = []
        for start in range(0, len(keys), 1024):
            locations = [doc.candidates[key] for key in keys[start : start + 1024]]
            scores.append(self.span_head(self.represent(hidden, locations)).float().sigmoid().cpu())
        ranked = []
        if scores:
            probs = torch.cat(scores)
            values, indices = probs.flatten().topk(min(limit, probs.numel()))
            for score, index in zip(values.tolist(), indices.tolist(), strict=True):
                span_idx, label_idx = divmod(index, len(SPAN_LABELS) - 1)
                ranked.append((score, (*keys[span_idx], SPAN_LABELS[label_idx + 1])))
        if suppress_same_type_overlap:
            ranked = keep_nonoverlapping(ranked)
        spans = {t: {s for confidence, s in ranked if confidence >= t} for t in thresholds}
        gold = {
            span_key(s) for s in doc.document.annotation.spans if (s.start, s.end) in doc.candidates
        }
        pairs = sorted(set(pair_keys(spans[min(thresholds)])) | set(pair_keys(gold)))
        links = {}
        for start in range(0, len(pairs), 1024):
            batch = pairs[start : start + 1024]
            probs = self.relations(doc, hidden, batch).float().softmax(dim=-1)
            values = probs[:, 1:]
            scores_and_labels = values.max(dim=-1)
            for pair, score, label in zip(
                batch,
                scores_and_labels.values.tolist(),
                scores_and_labels.indices.tolist(),
                strict=True,
            ):
                links[(*pair, LINK_LABELS[label + 1])] = score
        return spans, links


def decode(doc: TokenDocument, spans: set[SpanKey], links: set[LinkKey]) -> Annotation:
    """Build validated event predictions from exact evidence and supported date values."""
    return decode_notice(doc.document.notice, spans, links, "bamibert-prediction")


def decode_notice(
    notice: Notice, spans: set[SpanKey], links: set[LinkKey], annotator_id: str
) -> Annotation:
    """Build events on supplied notice offsets and validate their source evidence."""
    actions = {s for s in spans if s[2] == "ACTION"}
    used = actions | {b for _, b, _ in links}
    ids = {key: f"s{i}" for i, key in enumerate(sorted(used))}
    events = []
    links_by_action = defaultdict(list)
    for action, argument, role in sorted(links):
        links_by_action[action].append((argument, role))
    for i, action in enumerate(sorted(actions)):
        arguments = []
        evidence = {action}
        for key, role in links_by_action[action]:
            evidence.add(key)
            if key[2] == "TIME":
                value = notice.text[key[0] : key[1]]
                normalized, inferred = (None, False)
                if "/" in value or value.count("-") == 2:
                    normalized, inferred = normalize_date(value, notice.reference_date)
                arguments.append(
                    Argument(
                        span_id=ids[key], role=role, normalized_date=normalized, inferred=inferred
                    )
                )
            else:
                arguments.append(Argument(span_id=ids[key]))
        sentences = [
            s.sentence_id
            for s in notice.sentences
            if any(s.start <= start and end <= s.end for start, end, _ in evidence)
        ]
        events.append(
            Event(
                event_id=f"pred{i}",
                action_span_id=ids[action],
                arguments=arguments,
                evidence_sentence_ids=sentences,
            )
        )
    prediction = Annotation(
        doc_id=notice.doc_id,
        annotator_id=annotator_id,
        events=events,
        spans=[
            Span(span_id=ids[k], start=k[0], end=k[1], label=k[2], text=notice.text[k[0] : k[1]])
            for k in sorted(used)
        ],
    )
    validate_annotation(prediction, notice)
    return prediction
