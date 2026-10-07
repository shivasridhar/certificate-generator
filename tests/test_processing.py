import datetime
from pathlib import Path
import pytest

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate, RecipientIn
from app.services.jobs import create_job
from app.services.processing import process_job
import app.services.processing


@pytest.fixture(autouse=True)
def setup_processing_test_env(tmp_path, monkeypatch, session_factory):
    """
    Ensure all direct process_job invocations write to a temporary directory
    and use the isolated in-memory test database session factory.
    """
    monkeypatch.setattr("app.services.processing.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("app.services.processing.SessionLocal", session_factory)


def test_process_job_all_valid(db_session, tmp_path):
    """
    All-valid job:
    - process_job transitions status to 'completed'
    - succeeded == total, failed == 0
    - each certificate gets status 'success' and points to a real file on disk
    """
    payload = JobCreate(
        event_name="Full-Stack Python",
        issuer="Acme Tech",
        issue_date=datetime.date(2026, 10, 7),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com"),
            RecipientIn(name="Bob", email="bob@example.com"),
        ],
    )
    job = create_job(db=db_session, payload=payload)

    process_job(job.id)

    db_session.expire_all()
    updated_job = db_session.query(Job).filter(Job.id == job.id).first()
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.succeeded == 2
    assert updated_job.failed == 0
    assert updated_job.completed_at is not None

    certs = db_session.query(Certificate).filter(Certificate.job_id == job.id).all()
    assert len(certs) == 2
    for cert in certs:
        assert cert.status == CertificateStatus.SUCCESS
        assert cert.file_path is not None
        assert Path(cert.file_path).exists()


def test_process_job_mixed_creation(db_session):
    """
    Mixed job (some invalid at creation time):
    - Final status is 'completed_with_errors'
    - Counts reflect both succeeded and failed
    - Invalid certificates maintain their initial error message
    - Valid certificates succeed and have files created
    """
    payload = JobCreate(
        event_name="Cloud Security",
        issuer="Acme Security",
        issue_date=datetime.date(2026, 10, 7),
        recipients=[
            RecipientIn(name="Alice Valid", email="alice@example.com"),
            RecipientIn(name="   ", email="empty@example.com"),  # invalid: empty name
        ],
    )
    job = create_job(db=db_session, payload=payload)
    assert job.status == JobStatus.PENDING
    assert job.failed == 1

    process_job(job.id)

    db_session.expire_all()
    updated_job = db_session.query(Job).filter(Job.id == job.id).first()
    assert updated_job.status == JobStatus.COMPLETED_WITH_ERRORS
    assert updated_job.total == 2
    assert updated_job.succeeded == 1
    assert updated_job.failed == 1

    certs = db_session.query(Certificate).filter(Certificate.job_id == job.id).all()
    certs_by_name = {c.recipient_name: c for c in certs}

    assert certs_by_name["Alice Valid"].status == CertificateStatus.SUCCESS
    assert Path(certs_by_name["Alice Valid"].file_path).exists()

    assert certs_by_name[""].status == CertificateStatus.FAILED
    assert certs_by_name[""].error_message == "Name is empty"


def test_process_job_individual_generation_failure(db_session, monkeypatch):
    """
    Individual failure during PDF generation:
    - If one certificate generation raises an error, only that certificate fails
    - All other certificates succeed
    - Job status is 'completed_with_errors'
    """
    payload = JobCreate(
        event_name="Microservices",
        issuer="DevOps Institute",
        issue_date=datetime.date(2026, 10, 7),
        recipients=[
            RecipientIn(name="Alice Good", email="alice@example.com"),
            RecipientIn(name="Bob Crash", email="bob@example.com"),
            RecipientIn(name="Charlie Good", email="charlie@example.com"),
        ],
    )
    job = create_job(db=db_session, payload=payload)

    # Monkeypatch generate_certificate_pdf to fail ONLY for Bob Crash
    original_generate = app.services.processing.generate_certificate_pdf

    def faulty_generate(recipient_name, *args, **kwargs):
        if recipient_name == "Bob Crash":
            raise RuntimeError("Disk write permission denied")
        return original_generate(recipient_name, *args, **kwargs)

    monkeypatch.setattr(app.services.processing, "generate_certificate_pdf", faulty_generate)

    process_job(job.id)

    db_session.expire_all()
    updated_job = db_session.query(Job).filter(Job.id == job.id).first()
    assert updated_job.status == JobStatus.COMPLETED_WITH_ERRORS
    assert updated_job.total == 3
    assert updated_job.succeeded == 2
    assert updated_job.failed == 1

    certs = db_session.query(Certificate).filter(Certificate.job_id == job.id).all()
    certs_by_name = {c.recipient_name: c for c in certs}

    assert certs_by_name["Alice Good"].status == CertificateStatus.SUCCESS
    assert certs_by_name["Charlie Good"].status == CertificateStatus.SUCCESS
    assert certs_by_name["Bob Crash"].status == CertificateStatus.FAILED
    assert "Disk write permission denied" in certs_by_name["Bob Crash"].error_message


def test_process_job_all_generations_fail(db_session, monkeypatch):
    """When all PDF generations fail, final job status is 'failed'."""
    payload = JobCreate(
        event_name="Kubernetes",
        issuer="Cloud Native",
        issue_date=datetime.date(2026, 10, 7),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com"),
            RecipientIn(name="Bob", email="bob@example.com"),
        ],
    )
    job = create_job(db=db_session, payload=payload)

    def fail_always(*args, **kwargs):
        raise RuntimeError("ReportLab engine crashed")

    monkeypatch.setattr(app.services.processing, "generate_certificate_pdf", fail_always)

    process_job(job.id)

    db_session.expire_all()
    updated_job = db_session.query(Job).filter(Job.id == job.id).first()
    assert updated_job.status == JobStatus.FAILED
    assert updated_job.succeeded == 0
    assert updated_job.failed == 2


def test_process_job_not_pending_does_nothing(db_session, monkeypatch):
    """Calling process_job on a job that is already completed or processing does nothing."""
    payload = JobCreate(
        event_name="Event",
        issuer="Issuer",
        issue_date=datetime.date(2026, 10, 7),
        recipients=[RecipientIn(name="Alice", email="alice@example.com")],
    )
    job = create_job(db=db_session, payload=payload)
    job.status = JobStatus.COMPLETED
    db_session.commit()

    called = False

    def check_call(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(app.services.processing, "generate_certificate_pdf", check_call)

    process_job(job.id)
    assert not called


def test_process_job_non_existent_id_does_not_raise():
    """Calling process_job with an unknown UUID exits gracefully without raising an exception."""
    process_job("00000000-0000-0000-0000-000000000000")


def test_create_job_end_to_end_via_api(client, db_session):
    """
    End-to-end integration test:
    POST /jobs with valid recipients schedules background tasks.
    In FastAPI TestClient, background tasks run synchronously before returning.
    Assert that the job is completed and PDFs are generated.
    """
    payload = {
        "event_name": "FastAPI Masterclass",
        "issuer": "Modern Python Academy",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "E2E Alice", "email": "e2e_alice@example.com"},
            {"name": "E2E Bob", "email": "e2e_bob@example.com"},
        ],
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 202

    job_id = response.json()["id"]

    # Since TestClient executed the background task, the job should now be completed in DB
    db_session.expire_all()
    job = db_session.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert job.succeeded == 2
    assert job.failed == 0

    certs = db_session.query(Certificate).filter(Certificate.job_id == job_id).all()
    assert len(certs) == 2
    for cert in certs:
        assert cert.status == CertificateStatus.SUCCESS
        assert cert.file_path is not None
        assert Path(cert.file_path).exists()
