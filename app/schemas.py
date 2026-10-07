from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.config import MAX_RECIPIENTS_PER_JOB
from app.models import CertificateStatus, JobStatus


# ==============================================================================
# Input Schemas
# ==============================================================================

class RecipientIn(BaseModel):
    """
    Input schema for an individual certificate recipient.

    DESIGN DECISION:
    We deliberately keep 'name' and 'email' as plain strings here rather than
    enforcing strict validations (such as Pydantic's EmailStr or min_length=1)
    at the schema level.
    
    If we validated email format or non-empty strings here, any single typo or bad email
    in a batch of hundreds would cause Pydantic to reject the entire HTTP request
    with a 422 Unprocessable Entity error.
    
    By accepting plain strings at the API boundary, the overall bulk request succeeds,
    and our service layer will validate each recipient individually in the next step.
    Any invalid recipient will be marked with status='failed' and an explanatory
    error_message, while all valid recipients in the batch will continue to be
    processed and have certificates generated.
    """
    name: str
    email: str


class JobCreate(BaseModel):
    """
    Input payload for creating a new bulk certificate generation job.

    Structural validation is strictly enforced at this level:
    - Non-empty event_name and issuer.
    - Valid issue_date (formatted as YYYY-MM-DD).
    - recipients must contain between 1 and MAX_RECIPIENTS_PER_JOB items.
    """
    event_name: str = Field(..., min_length=1, description="Event or course title")
    issuer: str = Field(..., min_length=1, description="Issuing organization or authority")
    issue_date: date = Field(..., description="Issue date in YYYY-MM-DD format")
    recipients: list[RecipientIn] = Field(
        ...,
        min_length=1,
        description="List of recipients (minimum 1, maximum configured limit)",
    )

    @field_validator("event_name", "issuer")
    @classmethod
    def strip_and_validate_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return trimmed

    @field_validator("recipients")
    @classmethod
    def validate_recipients_count(cls, recipients: list[RecipientIn]) -> list[RecipientIn]:
        from app import config
        if len(recipients) > config.MAX_RECIPIENTS_PER_JOB:
            raise ValueError(
                f"Number of recipients ({len(recipients)}) exceeds maximum allowed "
                f"limit of {config.MAX_RECIPIENTS_PER_JOB} per job."
            )
        return recipients


# ==============================================================================
# Output / Response Schemas
# ==============================================================================

class CertificateOut(BaseModel):
    """Output representation of a single certificate."""
    id: str
    job_id: str
    recipient_name: str
    recipient_email: str
    status: CertificateStatus
    error_message: Optional[str] = None
    file_path: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def download_url(self) -> Optional[str]:
        """
        Direct URL to download this specific certificate.
        Only populated when the certificate status is 'success'.
        """
        if self.status == CertificateStatus.SUCCESS:
            return f"/certificates/{self.id}/download"
        return None


class JobOut(BaseModel):
    """Output representation of a job with summary counts, status, and progress."""
    id: str
    status: JobStatus
    event_name: str
    issuer: str
    issue_date: date
    total: int
    succeeded: int
    failed: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def progress_percent(self) -> float:
        """
        Calculates overall job completion as a percentage (0.0 to 100.0), rounded to 1 decimal place.

        DESIGN REASONING NOTE:
        The 'failed' counter encompasses recipients rejected upfront during initial job
        validation (such as malformed emails) as well as any runtime PDF rendering failures.
        Consequently, (succeeded + failed) accurately represents the count of recipients
        whose processing has fully resolved, reaching 100.0% when every certificate is handled.
        """
        if self.total <= 0:
            return 0.0
        return round(((self.succeeded + self.failed) / self.total) * 100.0, 1)


class JobDetailOut(JobOut):
    """Detailed job response including the list of all individual certificates."""
    certificates: list[CertificateOut] = []

    model_config = ConfigDict(from_attributes=True)
