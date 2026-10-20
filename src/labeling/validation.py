"""Reject annotations whose spans or event links cannot be traced to text."""

from smartnotice.schemas import Annotation, Notice


def validate_annotation(annotation: Annotation, notice: Notice) -> None:
    """Check unique identifiers, exact offsets, relation types, and evidence.

    Every linked span fits in a selected evidence sentence. TIME arguments
    require a role; other arguments cannot carry date metadata.
    """
    if annotation.doc_id != notice.doc_id:
        raise ValueError("Annotation document ID does not match the notice")
    spans = {span.span_id: span for span in annotation.spans}
    if len(spans) != len(annotation.spans):
        raise ValueError("Duplicate span ID")
    event_ids = [event.event_id for event in annotation.events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Duplicate event ID")
    for span in annotation.spans:
        if span.start >= span.end or notice.text[span.start : span.end] != span.text:
            raise ValueError(f"Invalid span offsets: {span.span_id}")
    sentences = {sentence.sentence_id: sentence for sentence in notice.sentences}
    for event in annotation.events:
        action = spans.get(event.action_span_id)
        if action is None or action.label != "ACTION":
            raise ValueError(f"Event {event.event_id} must reference an ACTION")
        if any(sid not in sentences for sid in event.evidence_sentence_ids):
            raise ValueError(f"Unknown evidence sentence in {event.event_id}")
        linked = [action]
        argument_ids = []
        for argument in event.arguments:
            span = spans.get(argument.span_id)
            if span is None or span.label == "ACTION":
                raise ValueError(f"Unknown or ACTION argument: {argument.span_id}")
            argument_ids.append(argument.span_id)
            if span.label == "TIME":
                if argument.role is None:
                    raise ValueError("TIME requires START, DEADLINE, or EVENT_TIME")
                if argument.inferred and (
                    argument.normalized_date is None or notice.reference_date is None
                ):
                    raise ValueError("An inferred date requires a date and reference date")
            elif argument.role or argument.normalized_date or argument.inferred:
                raise ValueError("Only TIME arguments carry date metadata")
            linked.append(span)
        if len(argument_ids) != len(set(argument_ids)):
            raise ValueError("Duplicate event argument")
        for span in linked:
            if not any(
                sentences[sid].start <= span.start and span.end <= sentences[sid].end
                for sid in event.evidence_sentence_ids
            ):
                raise ValueError(f"Missing evidence for span {span.span_id}")
    constrained = set()
    for constraint in annotation.audience_constraints:
        span = spans.get(constraint.audience_span_id)
        if span is None or span.label != "AUDIENCE":
            raise ValueError("Audience constraints require an AUDIENCE span")
        if constraint.audience_span_id in constrained:
            raise ValueError("Duplicate audience constraint")
        constrained.add(constraint.audience_span_id)
