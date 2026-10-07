import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class JobStatus(str, enum.Enum):
    """Lifecycle statuses for a bulk certificate generation job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class CertificateStatus(str, enum.Enum):
    """Lifecycle statuses for an individual certificate within a job."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


def generate_uuid() -> str:
    """Generate a standard UUID4 string for primary keys."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Generate a timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class Job(Base):
    """
    Represents a bulk certificate generation batch job.
    
    Tracks the overall event details, summary statistics (total, succeeded, failed),
    and execution timestamps.
    """
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    status = Column(
        SAEnum(JobStatus, native_enum=False),
        default=JobStatus.PENDING,
        nullable=False,
    )
    event_name = Column(String(255), nullable=False)
    issuer = Column(String(255), nullable=False)
    issue_date = Column(Date, nullable=False)
    total = Column(Integer, default=0, nullable=False)
    succeeded = Column(Integer, default=0, nullable=False)
    failed = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # 1-to-many relationship: A Job has many individual Certificates.
    # cascade="all, delete-orphan" ensures deleting a job removes its certificates.
    certificates = relationship(
        "Certificate",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Certificate.created_at",
    )


class Certificate(Base):
    """
    Represents an individual certificate belonging to a bulk Job.

    Stores recipient details, generation outcome (success or failed with error reason),
    and local file path to the generated PDF.
    """
    __tablename__ = "certificates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(
        String(36),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_name = Column(String(255), nullable=False)
    recipient_email = Column(String(255), nullable=False)
    status = Column(
        SAEnum(CertificateStatus, native_enum=False),
        default=CertificateStatus.PENDING,
        nullable=False,
    )
    error_message = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Many-to-1 relationship back to the parent Job
    job = relationship("Job", back_populates="certificates")
