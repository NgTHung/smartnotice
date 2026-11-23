from smartnotice.labeling.span_rules import SpanRules
from smartnotice.schemas import Annotation, Sentence, Span


def test_rules_keep_actions_dates_and_audiences_on_exact_source_offsets(notices):
    text = "Sinh viên K24 nộp hồ sơ trước 20/11 và đóng học phí trước 25/11."
    sentence = Sentence(sentence_id="s", text=text, start=0, end=len(text))
    notice = notices[0].model_copy(update={"text": text, "sentences": [sentence]})
    spans = {(text[a:b], label) for a, b, label in SpanRules().predict(notice)}
    assert spans >= {
        ("Sinh viên K24", "AUDIENCE"),
        ("nộp hồ sơ", "ACTION"),
        ("đóng học phí", "ACTION"),
        ("20/11", "TIME"),
        ("25/11", "TIME"),
    }


def test_phrases_require_two_training_notices_and_return_the_new_surface(notices):
    phrase = Span(span_id="p", text="Phiên 2024", start=0, end=10, label="DOCUMENT")
    first = Annotation(doc_id="first", annotator_id="fixture", events=[], spans=[phrase])
    second = first.model_copy(update={"doc_id": "second"})
    text = "Phiên 2026"
    notice = notices[0].model_copy(
        update={
            "text": text,
            "sentences": [Sentence(sentence_id="s", text=text, start=0, end=len(text))],
        }
    )
    rules = SpanRules()
    rules.fit_phrases([first])
    assert not rules.predict(notice, phrases=True)
    rules.fit_phrases([first, second])
    assert rules.predict(notice, phrases=True) == {(0, len(text), "DOCUMENT")}
    assert not rules.predict(notice)
