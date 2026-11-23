import pytest
from smartnotice.modeling.data import Document, labeled_links
from smartnotice.schemas import Annotation, Argument, Event, Sentence, Span

pytest.importorskip("torch")
pytest.importorskip("sklearn")
from smartnotice.modeling.contextual import (
    ContextExtractor,
    DocumentTemplateExtractor,
    TemplateExtractor,
)
from smartnotice.modeling.extraction import decode_notice


def test_context_pipeline_recovers_evidence_from_a_notice_without_annotations(notices):
    sentence = Sentence(sentence_id="s1", start=0, end=13, text="Nộp đơn 20/11")
    notice = notices[0].model_copy(update={"text": sentence.text, "sentences": [sentence]})
    spans = [
        Span(span_id="a", start=0, end=7, text="Nộp đơn", label="ACTION"),
        Span(span_id="t", start=8, end=13, text="20/11", label="TIME"),
    ]
    original = Annotation(
        doc_id=notice.doc_id,
        annotator_id="fixture",
        spans=spans,
        events=[
            Event(
                event_id="e",
                action_span_id="a",
                evidence_sentence_ids=["s1"],
                arguments=[Argument(span_id="t", role="DEADLINE")],
            )
        ],
    )
    model = ContextExtractor(42)
    model.fit([Document(notice, original, "fixture")])
    predicted = model.spans(notice)
    links = {link for link, score in model.links(notice, predicted) if score >= 0.5}
    result = decode_notice(notice, predicted, links, "context-prediction")
    assert labeled_links(result) == labeled_links(original)
    assert all(notice.text[s.start : s.end] == s.text for s in result.spans)
    sentence_model = TemplateExtractor(model, 0.65)
    docs = [Document(notice, original, "fixture")]
    sentence_model.fit(docs)
    doc_model = DocumentTemplateExtractor(sentence_model, 0.60)
    doc_model.fit(docs)
    changed = sentence.model_copy(update={"text": "Nộp đơn 25/12"})
    unseen = notice.model_copy(update={"text": changed.text, "sentences": [changed]})
    predicted, scored = doc_model.candidates(unseen)
    result = decode_notice(unseen, predicted, {k for k, v in scored if v >= 0.65}, "prediction")
    assert labeled_links(result) == labeled_links(original)
    assert "25/12" in {s.text for s in result.spans}
