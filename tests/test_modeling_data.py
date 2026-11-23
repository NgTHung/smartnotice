from smartnotice.modeling.data import Document, labeled_links, tokenize
from smartnotice.schemas import Annotation, Argument, Event, Sentence, Span


def test_candidate_offsets_deduplicate_overflow_and_respect_sentence_boundaries(notices):
    text = "A B C\nD E"
    notice = notices[0].model_copy(
        update={
            "text": text,
            "sentences": [
                Sentence(sentence_id="one", start=0, end=5, text="A B C"),
                Sentence(sentence_id="two", start=6, end=9, text="D E"),
            ],
        }
    )
    annotation = Annotation(doc_id=notice.doc_id, annotator_id="fixture", spans=[], events=[])

    def tokenizer(_text, **_kwargs):
        return {
            "input_ids": [[0, 10, 11, 12, 2], [0, 11, 12, 13, 14, 2]],
            "offset_mapping": [
                [(0, 0), (0, 1), (1, 3), (3, 5), (0, 0)],
                [(0, 0), (1, 3), (3, 5), (5, 7), (7, 9), (0, 0)],
            ],
        }

    token_doc = tokenize(Document(notice, annotation, "fixture"), tokenizer, 5, 2, 3)
    assert (4, 7) not in token_doc.candidates
    assert (6, 9) in token_doc.candidates
    assert token_doc.candidates[2, 3].window == 0
    assert token_doc.candidates[4, 5].window == 1


def test_shared_time_span_keeps_its_role_for_each_action():
    annotation = Annotation(
        doc_id="fixture",
        annotator_id="fixture",
        spans=[
            Span(span_id="a", start=0, end=3, text="Nộp", label="ACTION"),
            Span(span_id="b", start=4, end=7, text="Gửi", label="ACTION"),
            Span(span_id="t", start=8, end=13, text="20/11", label="TIME"),
        ],
        events=[
            Event(
                event_id="one",
                action_span_id="a",
                evidence_sentence_ids=["e"],
                arguments=[Argument(span_id="t", role="DEADLINE")],
            ),
            Event(
                event_id="two",
                action_span_id="b",
                evidence_sentence_ids=["e"],
                arguments=[Argument(span_id="t", role="START")],
            ),
        ],
    )
    assert labeled_links(annotation) == {
        ((0, 3, "ACTION"), (8, 13, "TIME"), "DEADLINE"),
        ((4, 7, "ACTION"), (8, 13, "TIME"), "START"),
    }
