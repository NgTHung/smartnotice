"""Own the document and annotation contracts used by every pipeline stage."""

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpanLabel = Literal["ACTION", "TIME", "AUDIENCE", "CONDITION", "CHANNEL", "DOCUMENT"]
TimeRole = Literal["START", "DEADLINE", "EVENT_TIME"]
GroupingField = Literal[
    "START",
    "END",
    "DEADLINE",
    "EVENT_TIME",
    "AUDIENCE",
    "CONDITION",
    "CHANNEL",
    "DOCUMENT",
    "LOCATION",
    "STATUS",
]
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


class EvidenceQuote(Record):
    """Reference an exact substring of one prepared source sentence."""

    doc_id: str
    sentence_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)


class ReviewAuthor(Record):
    """Attribute a review without treating assistant work as human approval."""

    reviewer_id: str = Field(min_length=1)
    reviewer_kind: Literal["ai_assistant", "human"]
    reviewed_at: datetime

    @model_validator(mode="after")
    def check_attribution(self):
        """Reject naive timestamps and assistant work attributed to a human."""
        if self.reviewed_at.utcoffset() is None:
            raise ValueError("Review time requires a timezone")
        if not self.reviewer_id.strip():
            raise ValueError("Review author requires a nonblank ID")
        if self.reviewer_kind == "human" and self.reviewer_id.strip().casefold() == "ai_assistant":
            raise ValueError("An assistant cannot supply human review")
        return self


class MentionVersion(Record):
    """Bind a document-local ACTION to immutable source and annotation hashes."""

    event_ref: str
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    annotation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class GroupingChange(Record):
    """Scope a supported old/new value to the updated mention's task.

    A null old quote records missing evidence; it never invents a prior value.
    LOCATION and STATUS are grouping fields, not new Annotation span labels.
    """

    field: GroupingField
    old: EvidenceQuote | None = None
    new: EvidenceQuote


class GroupingReview(Record):
    """Record an attributed pair decision and its task relation and changes."""

    review_id: str = Field(min_length=1)
    left: MentionVersion
    right: MentionVersion
    decision: Literal["SAME_EVENT", "UPDATE_OF", "DIFFERENT_EVENT", "UNCLEAR"]
    task_relation: Literal[
        "SAME_TASK",
        "DIFFERENT_TASK",
        "DIFFERENT_SESSION",
        "CONDITIONAL_TASK",
        "UNRESOLVED",
    ]
    author: ReviewAuthor
    rationale: str = Field(min_length=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)
    changes: list[GroupingChange] = Field(default_factory=list)
    notice_relation: Literal["REMINDER", "REPEATED_NOTICE", "UPDATE", "OTHER"] = "OTHER"

    @model_validator(mode="after")
    def check_decision(self):
        """Require directed changes for updates and consistent task relations."""
        if self.left.event_ref == self.right.event_ref:
            raise ValueError("A pair requires two different mentions")
        if self.decision == "UPDATE_OF":
            if self.task_relation != "SAME_TASK" or not self.changes:
                raise ValueError("UPDATE_OF requires the same task and explicit changes")
        elif self.changes:
            raise ValueError("Only UPDATE_OF carries changes")
        if self.decision in {"DIFFERENT_EVENT", "UNCLEAR"} and self.task_relation != "UNRESOLVED":
            raise ValueError("Separate or unclear groups cannot assert a task relation")
        return self


class TimeBoundaryReview(Record):
    """Interpret a TIME endpoint separately from the three Annotation time roles.

    END is an assembly boundary, not an accepted Annotation relation. Evidence
    is the referenced TIME span; the rationale explains its endpoint meaning.
    An optional value_key explicitly identifies complementary/repeated evidence
    of one temporal value within a task. The builder never infers these keys.
    """

    mention: MentionVersion
    span_id: str
    boundary: Literal["START", "END", "POINT"]
    author: ReviewAuthor
    rationale: str = Field(min_length=1)
    value_key: str | None = Field(default=None, min_length=1)


class AssemblyMention(Record):
    """Preserve source spans, arguments and sentences for one assembly member."""

    version: MentionVersion
    event: Event
    spans: list[Span]
    sentences: list[Sentence]
    annotation_origin: str


class GroupedFact(Record):
    """Preserve a source value and explicit supersession links without deletion."""

    fact_id: str
    mention_ref: str
    field: GroupingField
    quote: EvidenceQuote
    span_id: str | None = None
    normalized_date: date | None = None
    inferred: bool = False
    equivalence_key: str | None = None
    superseded_by: list[str] = Field(default_factory=list)


class GroupedTask(Record):
    """Keep a distinct task/session and its facts and unresolved active values."""

    task_id: str
    members: list[str]
    facts: list[GroupedFact]
    active_values: dict[GroupingField, list[str]]


class BuiltEventGroup(Record):
    """Contain provisional event identity with separate tasks and all notices."""

    group_id: str
    members: list[str]
    document_ids: list[str]
    tasks: list[GroupedTask]
    review_required: Literal[True] = True
    privacy_review_required: Literal[True] = True


class GroupConflict(Record):
    """Retain contradictions for review instead of guessing group or date values."""

    kind: Literal["group_contradiction", "task_contradiction", "competing_values"]
    members: list[str]
    review_ids: list[str] = Field(default_factory=list)
    field: GroupingField | None = None


class UpdateApplication(Record):
    """Record whether a directed field change reached a consistent shared task."""

    review_id: str
    field: GroupingField
    old_fact_ids: list[str]
    new_fact_id: str | None
    applied: bool


class EventGroupAssembly(Record):
    """Exchange versioned provisional groups, evidence, reviews and update history."""

    schema_version: Literal["event-groups-v1"] = "event-groups-v1"
    mentions: list[AssemblyMention]
    reviews: list[GroupingReview]
    time_boundaries: list[TimeBoundaryReview]
    groups: list[BuiltEventGroup]
    updates: list[UpdateApplication]
    conflicts: list[GroupConflict]


class GroupReviewNote(Record):
    """Preserve one user-authored group note exported by the local HTML viewer."""

    group_id: str = Field(min_length=1)
    status: Literal["not_seen", "looks_ok", "needs_check", "suggest_split"]
    text: str
    updated_at: datetime

    @model_validator(mode="after")
    def check_time(self):
        """Require the original note timestamp to identify its timezone."""
        if self.updated_at.utcoffset() is None:
            raise ValueError("Note time requires a timezone")
        return self


class LocalGroupReviewNotes(Record):
    """Bind exported draft group feedback to the exact assembly that was viewed."""

    kind: Literal["local_group_review_notes"]
    draft: Literal[True]
    assembly_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    exported_at: datetime
    entries: list[GroupReviewNote]

    @model_validator(mode="after")
    def check_notes(self):
        """Reject duplicate groups and timestamps incompatible with the export."""
        if self.exported_at.utcoffset() is None:
            raise ValueError("Export time requires a timezone")
        if len({e.group_id for e in self.entries}) != len(self.entries):
            raise ValueError("Duplicate group note")
        if any(e.updated_at > self.exported_at for e in self.entries):
            raise ValueError("Note cannot be newer than its export")
        return self


class GroupFeedbackResolution(Record):
    """Make a free-text split explicit without guessing partitions from prose.

    PARTITION must cover the old members exactly. SEPARATE_CONTENT preserves
    the old members while a caller adds separately validated source mentions.
    The resolution is an interpretation, not a new independent human review.
    """

    group_id: str
    mode: Literal["ACCEPT", "PARTITION", "SEPARATE_CONTENT"]
    partitions: list[list[str]] = Field(default_factory=list)
    additional_members: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class AppliedGroupFeedback(Record):
    """Keep the original user note and the assistant's explicit application."""

    note: GroupReviewNote
    outcome: Literal["accepted", "partitioned", "content_separated", "deferred", "not_reviewed"]
    partitions: list[list[str]]
    additional_members: list[str] = Field(default_factory=list)
    rationale: str
    affected_review_ids: list[str]
    application_author: ReviewAuthor


class GroupFeedbackResult(Record):
    """Exchange derived pair records and source-bound group feedback separately."""

    notes_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_assembly_fingerprint: str
    reviews: list[GroupingReview]
    applications: list[AppliedGroupFeedback]
    unreviewed_group_ids: list[str]


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
