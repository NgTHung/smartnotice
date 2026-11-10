"""Own the document and annotation contracts used by every pipeline stage."""

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpanLabel = Literal["ACTION", "TIME", "AUDIENCE", "CONDITION", "CHANNEL", "DOCUMENT"]
TimeRole = Literal["START", "DEADLINE", "EVENT_TIME"]
Applicability = Literal["APPLIES", "NOT_APPLIES", "UNCLEAR"]
Provider = Literal["gemini", "featherless"]
AudienceScope = Literal["all_students", "listed", "implicit", "outside_population"]
DegreeLevel = Literal["undergraduate", "master", "doctoral"]
StudentStatus = Literal["active", "on_leave", "suspended", "defended", "graduated"]


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
    """Encode one reviewed AUDIENCE span as profile requirements.

    Cohorts are integer admission years, given either as a list or as inclusive
    bounds. ``unrepresented`` marks a reviewed requirement that profiles cannot
    express, such as a class code. The data contract lists the permitted
    combinations of scope and attributes; others raise ``ValueError``.
    """

    audience_span_id: str
    scope: AudienceScope
    degree_levels: list[DegreeLevel] = Field(default_factory=list)
    cohorts: list[int] = Field(default_factory=list)
    cohort_min: int | None = None
    cohort_max: int | None = None
    majors: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    statuses: list[StudentStatus] = Field(default_factory=list)
    excluded_statuses: list[StudentStatus] = Field(default_factory=list)
    unrepresented: bool = False

    def has_inclusion(self) -> bool:
        """Return whether any inclusion attribute restricts the audience."""
        return bool(
            self.degree_levels
            or self.cohorts
            or self.cohort_min is not None
            or self.cohort_max is not None
            or self.majors
            or self.programs
            or self.statuses
        )

    @model_validator(mode="after")
    def check_scope(self):
        span = self.audience_span_id
        if self.cohorts and (self.cohort_min is not None or self.cohort_max is not None):
            raise ValueError(f"Use a cohort list or cohort bounds, not both: {span}")
        if (
            self.cohort_min is not None
            and self.cohort_max is not None
            and self.cohort_min > self.cohort_max
        ):
            raise ValueError(f"cohort_min exceeds cohort_max: {span}")
        if self.scope == "listed" and not (self.has_inclusion() or self.unrepresented):
            raise ValueError(f"A listed audience needs an attribute or unrepresented: {span}")
        if self.scope == "all_students" and self.has_inclusion():
            raise ValueError(f"An all_students audience has no inclusion attributes: {span}")
        if self.scope in {"implicit", "outside_population"} and (
            self.has_inclusion() or self.excluded_statuses or self.unrepresented
        ):
            raise ValueError(f"A {self.scope} audience carries no attributes: {span}")
        return self


class Annotation(Record):
    doc_id: str
    annotator_id: str
    spans: list[Span]
    events: list[Event]
    audience_constraints: list[AudienceConstraint] = Field(default_factory=list)


class Profile(Record):
    """Describe one synthetic student; ``cohort`` is an integer admission year."""

    profile_id: str
    cohort: int | None = None
    degree_level: DegreeLevel | None = None
    major: str | None = None
    program: str | None = None
    status: StudentStatus | None = None


class ProviderApproval(Record):
    """Record human clearance for one exact prepared text and named providers."""

    doc_id: str
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    providers: list[Provider] = Field(default_factory=list)
    privacy_cleared: bool
    provider_use_approved: bool


class PrivacyReviewItem(Record):
    """List one prepared text awaiting review; its approval template is not clearance."""

    doc_id: str
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_type: Literal["email", "web"]
    redaction_count: int = Field(ge=0)
    long_number_count: int = Field(ge=0)
    parser_warnings: list[str]
    attachments: list[str]
    text: str
    approval: dict


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
