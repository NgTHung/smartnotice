"""Exchange exact text spans and typed relations with Label Studio."""

from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import Annotation, Argument, Event, Notice, Span


def export_tasks(notices: list[Notice]) -> list[dict]:
    """Return unlabeled tasks with the immutable document and sentence metadata."""
    return [
        {
            "data": {
                "doc_id": notice.doc_id,
                "text": notice.text,
                "source_type": notice.source_type,
                "reference_date": str(notice.reference_date) if notice.reference_date else "",
                "sentences": [sentence.model_dump() for sentence in notice.sentences],
            }
        }
        for notice in notices
    ]


def import_tasks(tasks: list[dict], notices: list[Notice]) -> list[Annotation]:
    """Convert completed span/relation exports; require canonical-text equality.

    The UI collects spans and ACTION-to-argument links. Dates, reviewed evidence,
    and structured constraints are curated in canonical JSONL after conversion.
    Canceled annotations are skipped. Multiple annotators produce separate rows.
    """
    documents = {notice.doc_id: notice for notice in notices}
    output = []
    for task in tasks:
        doc_id = task["data"]["doc_id"]
        notice = documents[doc_id]
        if task["data"]["text"] != notice.text:
            raise ValueError(f"Label Studio text changed: {doc_id}")
        for item in task.get("annotations", []):
            if item.get("was_cancelled"):
                continue
            spans, relations = [], []
            for result in item.get("result", []):
                if result["type"] == "labels":
                    value = result["value"]
                    if len(value["labels"]) != 1:
                        raise ValueError("Each span requires exactly one label")
                    spans.append(
                        Span(
                            span_id=result["id"],
                            label=value["labels"][0],
                            start=value["start"],
                            end=value["end"],
                            text=value["text"],
                        )
                    )
                elif result["type"] == "relation":
                    relations.append(result)
            lookup = {span.span_id: span for span in spans}
            events = []
            for span in spans:
                if span.label != "ACTION":
                    continue
                arguments = []
                linked = [span]
                for relation in relations:
                    if relation["from_id"] != span.span_id:
                        continue
                    target = lookup[relation["to_id"]]
                    labels = relation.get("labels", [])
                    if len(labels) != 1:
                        raise ValueError("Each relation requires one relation label")
                    label = labels[0]
                    if target.label == "TIME":
                        arguments.append(Argument(span_id=target.span_id, role=label))
                    else:
                        if label != target.label:
                            raise ValueError("Relation label must match its argument type")
                        arguments.append(Argument(span_id=target.span_id))
                    linked.append(target)
                evidence = [
                    sentence.sentence_id
                    for sentence in notice.sentences
                    if any(sentence.start <= s.start and s.end <= sentence.end for s in linked)
                ]
                events.append(
                    Event(
                        event_id=f"e{len(events) + 1}",
                        action_span_id=span.span_id,
                        arguments=arguments,
                        evidence_sentence_ids=evidence,
                    )
                )
            for relation in relations:
                if (
                    relation["from_id"] not in lookup
                    or lookup[relation["from_id"]].label != "ACTION"
                ):
                    raise ValueError("Relations must originate from an ACTION")
            annotation = Annotation(
                doc_id=doc_id,
                annotator_id=str(item.get("completed_by", "unknown")),
                spans=spans,
                events=events,
            )
            validate_annotation(annotation, notice)
            output.append(annotation)
    return output
