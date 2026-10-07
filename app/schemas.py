from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
        max_length=MAX_RECIPIENTS_PER_JOB,
        description=f"List of recipients (between 1 and {MAX_RECIPIENTS_PER_JOB})",
    )

    @field_validator("event_name", "issuer")
    @classmethod
    def strip_and_validate_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return trimmed


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


class JobOut(BaseModel):
    """Output representation of a job with summary counts and status."""
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


class JobDetailOut(JobOut):
    """Detailed job response including the list of all individual certificates."""
    certificates: list[CertificateOut] = []

    model_config = ConfigDict(from_attributes=True)
