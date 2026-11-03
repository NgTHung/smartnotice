"""Own the document and annotation contracts used by every pipeline stage."""

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpanLabel = Literal["ACTION", "TIME", "AUDIENCE", "CONDITION", "CHANNEL", "DOCUMENT"]
TimeRole = Literal["START", "DEADLINE", "EVENT_TIME"]
Applicability = Literal["APPLIES", "NOT_APPLIES", "UNCLEAR"]
Provider = Literal["gemini", "featherless"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sentence(Record):
    sentence_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class PreparationFailure(Record):
    """Identify one rejected source using safe manifest and source references."""

    manifest_line: int = Field(ge=1)
    doc_id: str = Field(pattern=r"^[a-f0-9]{20}$")
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: Literal["empty_notice_body", "email_parse_failed", "web_parse_failed"]


class Notice(Record):
    """A prepared source with exact evidence offsets and redacted URL copies."""

    doc_id: str
    source_type: Literal["email", "web"]
    source_ref: str
    raw_sha256: str
    reference_date: date | None = None
    reference_date_origin: Literal["email_header", "published", "missing"]
    text: str
    attachments: list[str] = Field(default_factory=list)
    parser_warnings: list[str] = Field(default_factory=list)
    email_policy: Literal["all", "legacy"] = "all"
    privacy_rules_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    sentences: list[Sentence]
    group_id: str
    domain_holdout: bool = False
    synthetic: bool = False
    redaction_count: int = Field(ge=0)
    privacy_review_required: bool = True

    @model_validator(mode="after")
    def check_offsets(self):
        if len(self.attachments) != len(set(self.attachments)):
            raise ValueError("Attachment URLs must be unique")
        for link in self.attachments:
            try:
                parsed = urlsplit("https://" + link if link.lower().startswith("www.") else link)
                valid = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
            except ValueError:
                valid = False
            if not valid or any(char.isspace() for char in link) or link not in self.text:
                raise ValueError("Attachment URL must be a web link present in prepared text")
        for sentence in self.sentences:
            if self.text[sentence.start : sentence.end] != sentence.text:
                raise ValueError(f"Invalid sentence offsets: {sentence.sentence_id}")
        if self.domain_holdout and self.source_type != "web":
            raise ValueError("The domain holdout contains web notices only")
        return self


class Span(Record):
    span_id: str
    label: SpanLabel
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class Argument(Record):
    span_id: str
    role: TimeRole | None = None
    normalized_date: date | None = None
    inferred: bool = False


class Event(Record):
    event_id: str
    action_span_id: str
    arguments: list[Argument]
    evidence_sentence_ids: list[str] = Field(min_length=1)


class AudienceConstraint(Record):
    audience_span_id: str
    cohorts: list[str] = Field(default_factory=list)
    majors: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    excluded_statuses: list[str] = Field(default_factory=list)
    implicit: bool = False


class Annotation(Record):
    doc_id: str
    annotator_id: str
    spans: list[Span]
    events: list[Event]
    audience_constraints: list[AudienceConstraint] = Field(default_factory=list)


class Profile(Record):
    profile_id: str
    cohort: str | None = None
    major: str | None = None
    program: str | None = None
    status: str | None = None


class ProviderApproval(Record):
    """Record human clearance for one exact prepared text and named providers."""

    doc_id: str
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    providers: list[Provider] = Field(min_length=1)
    privacy_cleared: bool
    provider_use_approved: bool


class ProposalProvenance(Record):
    """Identify the source snapshot, prompt, parameters, and model suggestion."""

    schema_version: Literal[1] = 1
    run_id: str
    created_at: datetime
    provider: Provider
    model: str
    prompt_version: str
    prompt_sha256: str
    text_sha256: str
    raw_sha256: str
    prediction_sha256: str
    synthetic: bool
    temperature: float
    max_output_tokens: int


class ReviewRecord(Record):
    """Link an exported annotator decision to its original model suggestion."""

    doc_id: str
    run_id: str
    reviewer_id: str
    imported_at: datetime
    decision: Literal["accepted", "edited", "skipped"]
    provider: Provider
    model: str
    text_sha256: str
    prediction_sha256: str
    annotation_sha256: str | None = None
    synthetic: bool


class LabelingFailure(Record):
    """Record one failed labeling attempt without source text or response bodies."""

    doc_id: str
    provider: Provider
    model: str
    failed_at: datetime
    reason: str
