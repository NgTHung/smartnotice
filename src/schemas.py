"""Own the document and annotation contracts used by every pipeline stage."""

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpanLabel = Literal["ACTION", "TIME", "AUDIENCE", "CONDITION", "CHANNEL", "DOCUMENT"]
TimeRole = Literal["START", "DEADLINE", "EVENT_TIME"]
Applicability = Literal["APPLIES", "NOT_APPLIES", "UNCLEAR"]
Provider = Literal["gemini", "featherless"]
AuditSplit = Literal["train", "validation", "test", "domain_test", "excluded", "unassigned"]
AuditStatus = Literal["measured", "not_evaluable", "pending"]


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


class LMAuditContextRecord(Record):
    """Record one document's complete tokenizer input and simulated head cut."""

    run_id: str
    doc_id: str = Field(pattern=r"^[a-f0-9]{20}$")
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_type: Literal["email", "web"]
    split: AuditSplit
    synthetic: bool
    model_key: str
    model_id: str
    model_revision: str
    template_id: str
    template_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_limit: int = Field(gt=0)
    text_characters: int = Field(ge=0)
    text_tokens: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    prefix_tokens: int = Field(ge=0)
    special_tokens: int = Field(ge=0)
    overflow: bool
    head_input_tokens: int = Field(ge=0)
    source_tokens_retained_head: int = Field(ge=0)
    source_tokens_lost_head: int = Field(ge=0)
    status: Literal["measured", "tokenizer_error"]


class LMAuditURLRecord(Record):
    """Record context retention for one URL occurrence without storing its value."""

    run_id: str
    occurrence_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    document_url_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    url_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    doc_id: str = Field(pattern=r"^[a-f0-9]{20}$")
    source_type: Literal["email", "web"]
    split: AuditSplit
    synthetic: bool
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    model_key: str
    model_id: str
    model_revision: str
    template_id: str
    policy: str
    retention: Literal["retained", "partial", "lost"]


class LMAuditEvidenceRecord(Record):
    """Summarize annotation coverage by model, policy, label, and split."""

    run_id: str
    model_key: str
    model_id: str
    model_revision: str
    template_id: str
    policy: str
    source_type: Literal["email", "web"]
    split: AuditSplit
    synthetic: bool
    annotation_source: str
    unit: str
    label: str
    documents_with_annotations: int = Field(ge=0)
    units_total: int = Field(ge=0)
    fully_visible: int = Field(ge=0)
    partially_visible: int = Field(ge=0)
    not_visible: int = Field(ge=0)
    not_co_visible: int = Field(ge=0)
    status: AuditStatus


class PreprocessingAnomaly(Record):
    """Record a prepared-text finding with safe offsets and no text snippet."""

    doc_id: str = Field(pattern=r"^[a-f0-9]{20}$")
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_type: Literal["email", "web"]
    split: AuditSplit
    stage: str
    rule_id: str
    severity: Literal["info", "review", "critical"]
    confidence: Literal["high", "medium", "low"]
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)
    codepoint: str | None = None
    unicode_name: str | None = None
    occurrence_count: int = Field(default=1, ge=1)
    detail_code: str


class AuditReviewFinding(Record):
    """Point to one finding in a private human-review work item."""

    rule_id: str
    stage: str
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)
    severity: Literal["info", "review", "critical"]


class LMAuditReviewItem(Record):
    """Keep a private prepared document and its human review state pending."""

    doc_id: str = Field(pattern=r"^[a-f0-9]{20}$")
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_type: Literal["email", "web"]
    split: AuditSplit
    selection_method: Literal["flagged", "random_stratified"]
    strata: list[str] = Field(default_factory=list)
    findings: list[AuditReviewFinding] = Field(default_factory=list)
    text: str
    status: Literal["pending"] = "pending"
    decision: Literal["expected", "bug", "uncertain"] | None = None
    reason: str | None = None
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None


class LMAuditWindowRecord(Record):
    """Record window cost and global prepared-text character mapping."""

    run_id: str
    doc_id: str = Field(pattern=r"^[a-f0-9]{20}$")
    model_key: str
    model_id: str
    model_revision: str
    template_id: str
    policy: str
    window_id: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    body_token_start: int = Field(ge=0)
    body_token_end: int = Field(ge=0)
    source_char_ranges: list[tuple[int, int]] = Field(default_factory=list)
    source_offset_origin: Literal["prepared_text_codepoint"] = "prepared_text_codepoint"


class LanguageFinding(Record):
    """Locate a surface-language candidate without copying corpus text."""

    rule: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    lexicon_key: str | None = None


class LanguageDocumentStats(Record):
    """Bind surface counts to one prepared-text hash and inherited split."""

    doc_id: str
    text_sha256: str
    source_type: Literal["email", "web"]
    split: str
    synthetic: bool
    counts: dict[str, int]


class TokenBalanceRow(Record):
    """Count exclusive subword classes in the supplied annotated subset."""

    model_key: str
    source_type: str
    split: str
    synthetic: bool
    documents: int
    label: str
    count: int
    denominator: int
    share: float
    annotation_source: str = "human_annotation_valid_unadjudicated"
