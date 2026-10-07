import datetime
import pytest
from pydantic import ValidationError

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate, RecipientIn


def test_job_and_certificate_orm_models(db_session):
    """
    Verify that Job and Certificate ORM models persist to the database
    with proper foreign key relationships, default UUIDs, and enum statuses.
    """
    job = Job(
        event_name="FastAPI Workshop",
        issuer="Acme Academy",
        issue_date=datetime.date(2026, 10, 7),
        total=2,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.id is not None
    assert job.status == JobStatus.PENDING
    assert job.succeeded == 0
    assert job.failed == 0

    cert1 = Certificate(
        job_id=job.id,
        recipient_name="Alice Johnson",
        recipient_email="alice@example.com",
    )
    cert2 = Certificate(
        job_id=job.id,
        recipient_name="Bob Smith",
        recipient_email="bob@example.com",
    )
    db_session.add_all([cert1, cert2])
    db_session.commit()

    db_session.refresh(job)
    assert len(job.certificates) == 2
    assert job.certificates[0].recipient_name in ["Alice Johnson", "Bob Smith"]
    assert job.certificates[0].status == CertificateStatus.PENDING


def test_schema_structural_validation():
    """
    Verify that structurally invalid payloads are rejected with ValidationError (HTTP 422),
    while lenient RecipientIn accepts raw strings as intended.
    """
    # Valid payload
    valid_payload = JobCreate(
        event_name="FastAPI Mastery",
        issuer="Tech Institute",
        issue_date=datetime.date(2026, 10, 7),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com"),
            # Lenient schema: even if email is malformed or name is whitespace,
            # schema accepts it so the whole job is not aborted upfront.
            RecipientIn(name="   ", email="not-an-email"),
        ],
    )
    assert len(valid_payload.recipients) == 2

    # Structurally invalid: empty recipients list
    with pytest.raises(ValidationError):
        JobCreate(
            event_name="FastAPI Mastery",
            issuer="Tech Institute",
            issue_date=datetime.date(2026, 10, 7),
            recipients=[],
        )

    # Structurally invalid: empty event_name
    with pytest.raises(ValidationError):
        JobCreate(
            event_name="   ",
            issuer="Tech Institute",
            issue_date=datetime.date(2026, 10, 7),
            recipients=[RecipientIn(name="Alice", email="alice@example.com")],
        )
