"""Construct small, traceable synthetic applicability examples."""

from datetime import date
from hashlib import sha256
from random import Random

from smartnotice.labeling.pairs import build_pairs
from smartnotice.schemas import (
    Annotation,
    Argument,
    AudienceConstraint,
    Event,
    Notice,
    Profile,
    Sentence,
    Span,
)


def make_corpus(
    n_docs: int = 12, web_every: int = 2, seed: int = 42
) -> tuple[list[Notice], list[Annotation], list[Profile], list[dict], list[dict]]:
    """Return synthetic notices and pairs with three labels and shared groups."""
    rng = Random(seed)
    notices, annotations, assignments = [], [], []
    profiles = [
        Profile(profile_id="current", cohort=2024),
        Profile(profile_id="older", cohort=2023),
        Profile(profile_id="unknown"),
    ]
    for i in range(n_docs):
        source = "web" if i % web_every == 0 else "email"
        action = "Nộp hồ sơ" if rng.randrange(2) else "Đăng ký học phần"
        audience = "sinh viên K24"
        condition = "có chứng chỉ" if i % 4 == 3 else ""
        text = f"{action} cho {audience} {condition}".rstrip() + f" (ví dụ {i})."
        digest = sha256(text.encode("utf-8")).hexdigest()
        doc_id, group = digest[:20], f"g{i // 2}"
        notices.append(
            Notice(
                doc_id=doc_id,
                source_type=source,
                source_ref=f"synthetic:{i}",
                raw_sha256=digest,
                reference_date=date(2025, 10, 16),
                reference_date_origin="published" if source == "web" else "email_header",
                text=text,
                sentences=[Sentence(sentence_id="s1", start=0, end=len(text), text=text)],
                group_id=group,
                synthetic=True,
                redaction_count=0,
            )
        )
        spans = [
            Span(span_id="action", label="ACTION", text=action, start=0, end=len(action)),
            Span(
                span_id="audience",
                label="AUDIENCE",
                text=audience,
                start=text.index(audience),
                end=text.index(audience) + len(audience),
            ),
        ]
        if condition:
            start = text.index(condition)
            spans.append(
                Span(
                    span_id="condition",
                    label="CONDITION",
                    text=condition,
                    start=start,
                    end=start + len(condition),
                )
            )
        annotations.append(
            Annotation(
                doc_id=doc_id,
                annotator_id="synthetic",
                spans=spans,
                events=[
                    Event(
                        event_id="e1",
                        action_span_id="action",
                        arguments=[Argument(span_id=span.span_id) for span in spans[1:]],
                        evidence_sentence_ids=["s1"],
                    )
                ],
                audience_constraints=[
                    AudienceConstraint(audience_span_id="audience", scope="listed", cohorts=[2024])
                ],
            )
        )
        assignments.append(
            {"doc_id": doc_id, "group_id": group, "split": "validation" if i % 4 >= 2 else "train"}
        )
    pairs = build_pairs(notices, annotations, profiles)
    return notices, annotations, profiles, pairs, assignments
