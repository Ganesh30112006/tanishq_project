"""Shared enumerations.

These encode the domain vocabulary from the CareSense specification. They are
Django ``TextChoices`` so they can back model fields, be reused by DRF
serializers, and be imported by pure-Python service code without a DB.
"""
from __future__ import annotations

from django.db import models


class Role(models.TextChoices):
    PATIENT = "PATIENT", "Patient"
    DOCTOR = "DOCTOR", "Doctor"
    LAB_TECHNICIAN = "LAB_TECHNICIAN", "Lab technician"
    ADMIN = "ADMIN", "Administrator"


class ClinicalDataState(models.TextChoices):
    """Why a clinical value has (or lacks) a value. NULL alone is never enough
    to communicate clinical meaning (spec section 9).

    The ``OBSERVED`` / ``DERIVED`` / ``INFERRED`` / ``AI_GENERATED`` ladder is
    a one-way street: a value may be *demoted* in trust but is never promoted.
    Nothing in the system may rewrite an inferred or AI-generated value as an
    observed clinical fact (spec section 6).
    """

    OBSERVED = "OBSERVED", "Observed"
    DERIVED = "DERIVED", "Derived"
    INFERRED = "INFERRED", "Inferred"
    AI_GENERATED = "AI_GENERATED", "AI generated"
    NOT_REPORTED = "NOT_REPORTED", "Not reported"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"
    PENDING = "PENDING", "Pending"
    UNREADABLE = "UNREADABLE", "Unreadable"
    AMBIGUOUS = "AMBIGUOUS", "Ambiguous"
    CONFLICTING = "CONFLICTING", "Conflicting"
    INVALID = "INVALID", "Invalid"
    MISSING = "MISSING", "Missing"


# A value may only be treated as trustworthy evidence in these states. Note
# that INFERRED and AI_GENERATED are deliberately excluded: a trend or an LLM
# summary is never model-grade input evidence (spec sections 6, 14, 36).
TRUSTWORTHY_CLINICAL_STATES = frozenset({ClinicalDataState.OBSERVED, ClinicalDataState.DERIVED})

# States that carry clinical content but must never be treated as measured
# fact. Kept explicit so callers cannot silently widen the trusted set.
UNTRUSTED_CONTENT_STATES = frozenset(
    {ClinicalDataState.INFERRED, ClinicalDataState.AI_GENERATED}
)


class ModelLifecycleState(models.TextChoices):
    """Governed lifecycle of a clinical prediction model (spec sections 5, 54).

    A model does not become usable because its tests pass; it becomes usable
    because a human approver moved it through this lifecycle with recorded
    evidence. Only ``APPROVED_FOR_CLINICAL_REVIEW`` may back a live task.
    """

    DRAFT = "DRAFT", "Draft"
    VALIDATION = "VALIDATION", "Technical validation"
    APPROVED_FOR_EVALUATION = "APPROVED_FOR_EVALUATION", "Approved for evaluation (shadow)"
    APPROVED_FOR_CLINICAL_REVIEW = (
        "APPROVED_FOR_CLINICAL_REVIEW",
        "Approved for clinical decision support",
    )
    REJECTED = "REJECTED", "Rejected"
    RETIRED = "RETIRED", "Retired"


class AssessmentLifecycleState(models.TextChoices):
    """Lifecycle of a single risk assessment (spec section 40).

    Not every risk calculation is a finalized clinical assessment. The state
    records exactly how far a given request got and whether a clinician still
    needs to look at it.
    """

    REQUESTED = "REQUESTED", "Requested"
    VALIDATING = "VALIDATING", "Validating evidence"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA", "Insufficient data (safe outcome)"
    READY_FOR_INFERENCE = "READY_FOR_INFERENCE", "Ready for inference"
    INFERENCE_COMPLETE = "INFERENCE_COMPLETE", "Inference complete"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "Clinical review required"
    CLINICALLY_REVIEWED = "CLINICALLY_REVIEWED", "Clinically reviewed"
    FINALIZED = "FINALIZED", "Finalized"
    CANCELLED = "CANCELLED", "Cancelled"


class ClinicalReviewDecision(models.TextChoices):
    """A clinician's recorded decision on a model output (spec section 39)."""

    ACCEPTED = "ACCEPTED", "Accepted as decision support"
    REJECTED = "REJECTED", "Rejected"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA", "Needs more data"
    ESCALATED = "ESCALATED", "Escalated"


class ExtractionMethod(models.TextChoices):
    MANUAL_ENTRY = "MANUAL_ENTRY", "Manual entry"
    STRUCTURED_IMPORT = "STRUCTURED_IMPORT", "Structured import"
    OCR = "OCR", "OCR"
    NLP = "NLP", "NLP entity extraction"
    DERIVED = "DERIVED", "Derived / computed"


class ValidationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PASSED = "PASSED", "Passed"
    FAILED = "FAILED", "Failed"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "Review required"


class ReportClass(models.TextChoices):
    CBC = "CBC", "Complete blood count"
    LIPID = "LIPID", "Lipid profile"
    GLUCOSE = "GLUCOSE", "Glucose"
    HBA1C = "HBA1C", "HbA1c"
    LIVER = "LIVER", "Liver function"
    KIDNEY = "KIDNEY", "Kidney function"
    URINALYSIS = "URINALYSIS", "Urinalysis"
    PATHOLOGY = "PATHOLOGY", "Pathology"
    RADIOLOGY = "RADIOLOGY", "Radiology"
    PRESCRIPTION = "PRESCRIPTION", "Prescription"
    DISCHARGE = "DISCHARGE", "Discharge summary"
    CLINICAL_NOTE = "CLINICAL_NOTE", "Clinical note"
    OTHER = "OTHER", "Other / unclassified"


class ReportProcessingState(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    VALIDATING_FILE = "VALIDATING_FILE", "Validating file"
    EXTRACTING = "EXTRACTING", "Extracting"
    CLASSIFYING = "CLASSIFYING", "Classifying"
    STRUCTURING = "STRUCTURING", "Structuring"
    RECONCILING = "RECONCILING", "Reconciling"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "Human review required"
    FINALIZED = "FINALIZED", "Finalized"
    REJECTED = "REJECTED", "Rejected"


class CompletenessStatus(models.TextChoices):
    COMPLETE = "COMPLETE", "Complete"
    INCOMPLETE = "INCOMPLETE", "Incomplete"
    AMBIGUOUS = "AMBIGUOUS", "Ambiguous"
    INVALID = "INVALID", "Invalid"
    CONFLICTING = "CONFLICTING", "Conflicting"


class DataSufficiency(models.TextChoices):
    SUFFICIENT = "SUFFICIENT", "Sufficient"
    PARTIALLY_SUFFICIENT = "PARTIALLY_SUFFICIENT", "Partially sufficient"
    INSUFFICIENT = "INSUFFICIENT", "Insufficient"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN", "Out of domain"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "Review required"


class ReliabilityStatus(models.TextChoices):
    """Result of the out-of-distribution / reliability check (spec section 32)."""

    VALID = "VALID", "Valid"
    LOW_RELIABILITY = "LOW_RELIABILITY", "Low reliability"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN", "Out of domain"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA", "Insufficient data"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "Review required"


class LookupState(models.TextChoices):
    """Outcome of searching the full authorized record for a required value
    before raising a missing-data task (spec sections 22 and 51)."""

    FOUND = "FOUND", "Found"
    OUTDATED = "OUTDATED", "Outdated"
    NOT_FOUND = "NOT_FOUND", "Not found"
    INVALID = "INVALID", "Invalid"
    CONFLICTING = "CONFLICTING", "Conflicting"
    PENDING = "PENDING", "Pending"
    UNREADABLE = "UNREADABLE", "Unreadable"


class MissingDataTaskStatus(models.TextChoices):
    MISSING = "MISSING", "Missing"
    NOTIFIED = "NOTIFIED", "Notified"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    RESOLVED = "RESOLVED", "Resolved"
    CLOSED = "CLOSED", "Closed"
    CANCELLED = "CANCELLED", "Cancelled"


class JobState(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    RUNNING = "RUNNING", "Running"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    RETRYING = "RETRYING", "Retrying"
    CANCELLED = "CANCELLED", "Cancelled"


class AnomalyMethod(models.TextChoices):
    IQR = "IQR", "Interquartile range"
    MAD = "MAD", "Median absolute deviation"
    ISOLATION_FOREST = "ISOLATION_FOREST", "Isolation forest"
    TEMPORAL_BASELINE = "TEMPORAL_BASELINE", "Temporal baseline deviation"


class ReviewStatus(models.TextChoices):
    NOT_REQUIRED = "NOT_REQUIRED", "Not required"
    PENDING = "PENDING", "Pending review"
    IN_REVIEW = "IN_REVIEW", "In review"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"


class AuditResult(models.TextChoices):
    SUCCESS = "SUCCESS", "Success"
    DENIED = "DENIED", "Denied"
    ERROR = "ERROR", "Error"


class ReconciliationStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_REVIEW = "IN_REVIEW", "In review"
    RESOLVED = "RESOLVED", "Resolved"
    DISMISSED = "DISMISSED", "Dismissed"
