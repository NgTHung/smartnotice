"""Own the document and annotation contracts used by every pipeline stage."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpanLabel = Literal["ACTION", "TIME", "AUDIENCE", "CONDITION", "CHANNEL", "DOCUMENT"]
TimeRole = Literal["START", "DEADLINE", "EVENT_TIME"]
Applicability = Literal["APPLIES", "NOT_APPLIES", "UNCLEAR"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CrawlCandidate(Record):
    """Describe a discovered URL and its deterministic title selection decision."""

    url: str
    title: str
    selection_reason: str


class CrawlIndex(Record):
    """Connect an accepted source snapshot to its prepared text and pending reviews."""

    doc_id: str
    raw_sha256: str
    requested_url: str
    url: str
    title: str
    listing_title: str
    institution: Literal["HCMUS"] = "HCMUS"
    raw_path: str
    snapshot_path: str
    selector: str
    characters: int = Field(gt=0)
    prepared_text_sha256: str
    publication_date_candidate: date | None = None
    publication_date_display: str | None = None
    published_time_metadata: str | None = None
    publication_date_status: Literal["unverified", "missing", "invalid", "conflict"]
    reference_date: date | None = None
    privacy_review_required: bool = True
    date_review_required: bool = True
    content_review_required: bool = True
    warnings: list[str] = Field(default_factory=list)


class CrawlLog(Record):
    """Record one listing or detail outcome without copying its source text."""

    kind: Literal["listing", "detail", "preparation"]
    requested_url: str
    url: str | None = None
    status: Literal["fetched", "accepted", "skipped", "failed"]
    reason: str
    snapshot_path: str | None = None
    doc_id: str | None = None
    duplicate_of: str | None = None


class CrawlSummary(Record):
    """Report software collection counts, separate from human review or model quality."""

    run_id: str
    source: Literal["hcmus-student"] = "hcmus-student"
    listing_url: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "complete", "partial", "failed", "interrupted"] = "running"
    complete: bool = False
    target: int = Field(gt=0)
    max_candidates: int = Field(gt=0)
    interval_seconds: float = Field(ge=1)
    short_text_threshold: int = Field(gt=0)
    domain_holdout: bool
    discovered_links: int = Field(default=0, ge=0)
    eligible_candidates: int = Field(default=0, ge=0)
    attempted_details: int = Field(default=0, ge=0)
    accepted: int = Field(default=0, ge=0)
    unique_prepared_texts: int = Field(default=0, ge=0)
    missing_reference_dates: int = Field(default=0, ge=0)
    privacy_review_required: int = Field(default=0, ge=0)
    date_review_required: int = Field(default=0, ge=0)
    content_review_required: int = Field(default=0, ge=0)
    outcome_counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class Sentence(Record):
    sentence_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class Notice(Record):
    doc_id: str
    source_type: Literal["email", "web"]
    source_ref: str
    raw_sha256: str
    reference_date: date | None = None
    reference_date_origin: Literal["email_header", "published", "missing"]
    text: str
    sentences: list[Sentence]
    group_id: str
    domain_holdout: bool = False
    synthetic: bool = False
    redaction_count: int = Field(ge=0)
    privacy_review_required: bool = True

    @model_validator(mode="after")
    def check_offsets(self):
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
