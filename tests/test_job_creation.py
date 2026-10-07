import pytest

from app.models import Certificate, CertificateStatus, JobStatus
from app.schemas import RecipientIn
from app.services.validation import validate_recipients


# ==============================================================================
# Unit Tests for validate_recipients
# ==============================================================================

def test_validate_recipients_whitespace_only_name():
    """Verify that a name containing only whitespace fails with 'Name is empty'."""
    results = validate_recipients([
        RecipientIn(name="    ", email="alice@example.com")
    ])
    assert len(results) == 1
    assert not results[0].is_valid
    assert results[0].error == "Name is empty"


def test_validate_recipients_101_char_name():
    """Verify that a name exceeding 100 characters fails with length error."""
    long_name = "A" * 101
    results = validate_recipients([
        RecipientIn(name=long_name, email="alice@example.com")
    ])
    assert len(results) == 1
    assert not results[0].is_valid
    assert results[0].error == "Name exceeds 100 characters"


def test_validate_recipients_duplicate_email_case_insensitive():
    """Verify that duplicate emails in the same batch are detected case-insensitively."""
    results = validate_recipients([
        RecipientIn(name="Alice First", email="ALICE@example.com"),
        RecipientIn(name="Alice Second", email="alice@EXAMPLE.COM"),
    ])
    assert len(results) == 2
    # First occurrence is valid
    assert results[0].is_valid
    assert results[0].error is None
    # Second occurrence fails as duplicate
    assert not results[1].is_valid
    assert results[1].error == "Duplicate email in request"


# ==============================================================================
# Integration Tests for POST /jobs Endpoint
# ==============================================================================

def test_create_job_valid_three_recipients(client, db_session):
    """
    Test a valid request with 3 recipients:
    - HTTP 202 Accepted
    - Total: 3, Succeeded: 0, Failed: 0, Status: pending
    - 3 Certificate rows created in DB with status 'pending'
    """
    payload = {
        "event_name": "Advanced Python Workshop",
        "issuer": "Python Institute",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "Alice Johnson", "email": "alice@example.com"},
            {"name": "Bob Smith", "email": "bob@example.com"},
            {"name": "Charlie Davis", "email": "charlie@example.com"},
        ],
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 202

    data = response.json()
    assert data["id"] is not None
    assert data["event_name"] == "Advanced Python Workshop"
    assert data["issuer"] == "Python Institute"
    assert data["issue_date"] == "2026-10-07"
    assert data["status"] == "pending"
    assert data["total"] == 3
    assert data["succeeded"] == 0
    assert data["failed"] == 0
    assert data["completed_at"] is None

    # Check database rows
    job_id = data["id"]
    certs = db_session.query(Certificate).filter_by(job_id=job_id).all()
    assert len(certs) == 3
    for cert in certs:
        assert cert.status == CertificateStatus.PENDING
        assert cert.error_message is None


def test_create_job_mixed_recipients(client, db_session):
    """
    Test mixed request:
    - 1 valid
    - 1 empty name
    - 1 bad email
    - 1 duplicate email
    Result: 202, total=4, failed=3, and each failed certificate has the exact reason.
    """
    payload = {
        "event_name": "Cloud Architecture Masterclass",
        "issuer": "Cloud Academy",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "Valid Recipient", "email": "valid@example.com"},
            {"name": "   ", "email": "emptyname@example.com"},
            {"name": "Bad Email Recipient", "email": "not-an-email"},
            {"name": "Duplicate Recipient", "email": "VALID@example.com"},
        ],
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 202

    data = response.json()
    assert data["total"] == 4
    assert data["failed"] == 3
    assert data["succeeded"] == 0
    assert data["status"] == "pending"  # 1 valid recipient remains to be processed

    job_id = data["id"]
    certs = db_session.query(Certificate).filter_by(job_id=job_id).all()
    assert len(certs) == 4

    certs_by_email = {c.recipient_email: c for c in certs}

    # 1. Valid recipient
    assert certs_by_email["valid@example.com"].status == CertificateStatus.PENDING
    assert certs_by_email["valid@example.com"].error_message is None

    # 2. Empty name
    assert certs_by_email["emptyname@example.com"].status == CertificateStatus.FAILED
    assert certs_by_email["emptyname@example.com"].error_message == "Name is empty"

    # 3. Bad email
    assert certs_by_email["not-an-email"].status == CertificateStatus.FAILED
    assert certs_by_email["not-an-email"].error_message == "Invalid email format"

    # 4. Duplicate email
    assert certs_by_email["VALID@example.com"].status == CertificateStatus.FAILED
    assert certs_by_email["VALID@example.com"].error_message == "Duplicate email in request"


def test_create_job_all_invalid_recipients(client, db_session):
    """
    Test when all recipients fail validation:
    - Job status is immediately 'failed'
    - completed_at timestamp is populated
    - total=2, failed=2
    """
    payload = {
        "event_name": "Webinar",
        "issuer": "Tech Corp",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "   ", "email": "test1@example.com"},
            {"name": "Alice", "email": "not-an-email"},
        ],
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 202

    data = response.json()
    assert data["status"] == "failed"
    assert data["total"] == 2
    assert data["failed"] == 2
    assert data["succeeded"] == 0
    assert data["completed_at"] is not None


def test_empty_recipients_list_returns_422(client):
    """Empty recipients list is structurally invalid and must return 422."""
    payload = {
        "event_name": "Workshop",
        "issuer": "Tech Corp",
        "issue_date": "2026-10-07",
        "recipients": [],
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 422


def test_missing_event_name_returns_422(client):
    """Missing required template metadata (event_name) must return 422."""
    payload = {
        "issuer": "Tech Corp",
        "issue_date": "2026-10-07",
        "recipients": [{"name": "Alice", "email": "alice@example.com"}],
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 422


def test_more_than_max_recipients_returns_422(client, monkeypatch):
    """Exceeding MAX_RECIPIENTS_PER_JOB must fail with 422."""
    monkeypatch.setattr("app.config.MAX_RECIPIENTS_PER_JOB", 2)
    payload = {
        "event_name": "Workshop",
        "issuer": "Tech Corp",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
            {"name": "Charlie", "email": "charlie@example.com"},
        ],
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 422
