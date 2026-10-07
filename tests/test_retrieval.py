import datetime
import io
import os
from pathlib import Path
import zipfile
import pytest

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate, RecipientIn
from app.services.jobs import create_job


# ==============================================================================
# 1. Job Status and Progress Endpoint Tests
# ==============================================================================

def test_get_job_fully_completed(client):
    """
    Test GET /jobs/{job_id} for a completed job:
    - Status is 'completed'
    - progress_percent is 100.0
    - Each certificate has a valid download_url
    """
    payload = {
        "event_name": "Full-Stack Python Summit",
        "issuer": "Tech Institute",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "Alice Johnson", "email": "alice@example.com"},
            {"name": "Bob Smith", "email": "bob@example.com"},
        ],
    }
    create_res = client.post("/jobs", json=payload)
    assert create_res.status_code == 202
    job_id = create_res.json()["id"]

    # Since TestClient processes background tasks before returning, job is completed
    res = client.get(f"/jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == job_id
    assert data["status"] == "completed"
    assert data["progress_percent"] == 100.0
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    assert len(data["certificates"]) == 2

    for cert in data["certificates"]:
        assert cert["status"] == "success"
        assert cert["download_url"] == f"/certificates/{cert['id']}/download"


def test_get_job_pending_zero_progress(client, monkeypatch):
    """
    Test GET /jobs/{job_id} when job is still pending:
    - progress_percent is 0.0
    - Certificates are status 'pending' with download_url == None
    """
    # Disable background worker to capture state while still pending
    monkeypatch.setattr("app.routers.jobs.process_job", lambda job_id: None)

    payload = {
        "event_name": "Async Workshop",
        "issuer": "Async Org",
        "issue_date": "2026-10-07",
        "recipients": [{"name": "Pending User", "email": "pending@example.com"}],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    res = client.get(f"/jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pending"
    assert data["progress_percent"] == 0.0
    assert len(data["certificates"]) == 1
    assert data["certificates"][0]["status"] == "pending"
    assert data["certificates"][0]["download_url"] is None


def test_job_progress_mid_run(client, db_session):
    """
    Verify progress_percent computation mid-run:
    - (succeeded + failed) / total * 100, rounded to 1 decimal
    - For total=4, succeeded=2, failed=1 -> 3/4 = 75.0%
    """
    job = Job(
        event_name="Ongoing Webinar",
        issuer="Webinar Academy",
        issue_date=datetime.date(2026, 10, 7),
        total=4,
        succeeded=2,
        failed=1,
        status=JobStatus.PROCESSING,
    )
    db_session.add(job)
    db_session.commit()

    res = client.get(f"/jobs/{job.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "processing"
    assert data["progress_percent"] == 75.0


def test_get_job_mixed_results(client):
    """
    Test mixed job:
    - Failed certificates show their error_message and download_url == None
    - Valid certificates have status 'success' and a valid download_url
    - progress_percent reaches 100.0 because all recipients are handled
    """
    payload = {
        "event_name": "Mixed Workshop",
        "issuer": "Issuer Inc",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "Valid User", "email": "valid@example.com"},
            {"name": "   ", "email": "empty_name@example.com"},
        ],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    res = client.get(f"/jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed_with_errors"
    assert data["progress_percent"] == 100.0

    certs = {c["recipient_email"]: c for c in data["certificates"]}
    assert certs["valid@example.com"]["status"] == "success"
    assert certs["valid@example.com"]["download_url"] is not None

    assert certs["empty_name@example.com"]["status"] == "failed"
    assert certs["empty_name@example.com"]["error_message"] == "Name is empty"
    assert certs["empty_name@example.com"]["download_url"] is None


def test_unknown_job_id_returns_404(client):
    """Unknown job ID must return 404 across all job-specific endpoints."""
    bad_id = "00000000-0000-0000-0000-000000000000"

    res_detail = client.get(f"/jobs/{bad_id}")
    assert res_detail.status_code == 404

    res_certs = client.get(f"/jobs/{bad_id}/certificates")
    assert res_certs.status_code == 404

    res_zip = client.get(f"/jobs/{bad_id}/download")
    assert res_zip.status_code == 404


# ==============================================================================
# 2. Certificate Listing & Pagination Tests
# ==============================================================================

def test_list_job_certificates_filtering_and_pagination(client):
    """
    Test GET /jobs/{id}/certificates:
    - Status filtering (status=success vs status=failed)
    - Pagination limit & offset
    - Invalid status value returns 422
    """
    payload = {
        "event_name": "Pagination Workshop",
        "issuer": "Paging Academy",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "User One", "email": "u1@example.com"},
            {"name": "User Two", "email": "u2@example.com"},
            {"name": "   ", "email": "bad@example.com"},
        ],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    # 1. Filter by status=success (should be 2)
    res_success = client.get(f"/jobs/{job_id}/certificates?status=success")
    assert res_success.status_code == 200
    assert len(res_success.json()) == 2
    for cert in res_success.json():
        assert cert["status"] == "success"

    # 2. Filter by status=failed (should be 1)
    res_failed = client.get(f"/jobs/{job_id}/certificates?status=failed")
    assert res_failed.status_code == 200
    assert len(res_failed.json()) == 1
    assert res_failed.json()[0]["status"] == "failed"

    # 3. Pagination: limit=1, offset=0 then offset=1
    res_p1 = client.get(f"/jobs/{job_id}/certificates?limit=1&offset=0")
    res_p2 = client.get(f"/jobs/{job_id}/certificates?limit=1&offset=1")
    assert res_p1.status_code == 200
    assert res_p2.status_code == 200
    assert len(res_p1.json()) == 1
    assert len(res_p2.json()) == 1
    assert res_p1.json()[0]["id"] != res_p2.json()[0]["id"]

    # 4. Invalid status filter returns 422
    res_invalid_status = client.get(f"/jobs/{job_id}/certificates?status=not_a_valid_status")
    assert res_invalid_status.status_code == 422


# ==============================================================================
# 3. Single Certificate Download Tests
# ==============================================================================

def test_single_certificate_download_success(client):
    """
    Test GET /certificates/{id}/download for a successful certificate:
    - HTTP 200 OK
    - Content-Type application/pdf
    - Body starts with magic bytes %PDF
    """
    payload = {
        "event_name": "Download Test",
        "issuer": "Issuer",
        "issue_date": "2026-10-07",
        "recipients": [{"name": "Download User", "email": "download@example.com"}],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    job_res = client.get(f"/jobs/{job_id}")
    cert_id = job_res.json()["certificates"][0]["id"]

    download_res = client.get(f"/certificates/{cert_id}/download")
    assert download_res.status_code == 200
    assert download_res.headers["content-type"] == "application/pdf"
    assert download_res.content.startswith(b"%PDF")


def test_download_failed_certificate_returns_409(client):
    """Downloading a certificate with status 'failed' returns 409 with error detail."""
    payload = {
        "event_name": "Failed Test",
        "issuer": "Issuer",
        "issue_date": "2026-10-07",
        "recipients": [{"name": "   ", "email": "bad@example.com"}],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    job_res = client.get(f"/jobs/{job_id}")
    cert_id = job_res.json()["certificates"][0]["id"]

    download_res = client.get(f"/certificates/{cert_id}/download")
    assert download_res.status_code == 409
    assert "Name is empty" in download_res.json()["detail"]


def test_download_pending_certificate_returns_409(client, monkeypatch):
    """Downloading a certificate while it is still 'pending' returns 409."""
    monkeypatch.setattr("app.routers.jobs.process_job", lambda job_id: None)

    payload = {
        "event_name": "Pending Test",
        "issuer": "Issuer",
        "issue_date": "2026-10-07",
        "recipients": [{"name": "Pending User", "email": "pending@example.com"}],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    job_res = client.get(f"/jobs/{job_id}")
    cert_id = job_res.json()["certificates"][0]["id"]

    download_res = client.get(f"/certificates/{cert_id}/download")
    assert download_res.status_code == 409
    assert "not ready yet" in download_res.json()["detail"].lower()


def test_download_file_deleted_from_disk_returns_404(client, db_session):
    """If a certificate has status 'success' but file was removed from disk, return 404."""
    payload = {
        "event_name": "Delete Test",
        "issuer": "Issuer",
        "issue_date": "2026-10-07",
        "recipients": [{"name": "User", "email": "user@example.com"}],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    cert = db_session.query(Certificate).filter_by(job_id=job_id).first()
    # Delete the generated file from disk
    if cert.file_path and os.path.exists(cert.file_path):
        os.unlink(cert.file_path)

    download_res = client.get(f"/certificates/{cert.id}/download")
    assert download_res.status_code == 404
    assert "not found" in download_res.json()["detail"].lower()


def test_download_unknown_certificate_returns_404(client):
    """Downloading a non-existent certificate UUID returns 404."""
    res = client.get("/certificates/00000000-0000-0000-0000-000000000000/download")
    assert res.status_code == 404


# ==============================================================================
# 4. Job ZIP Download Tests
# ==============================================================================

def test_job_zip_download_success_and_sanitization(client):
    """
    Test GET /jobs/{id}/download:
    - Returns valid ZIP
    - Contains exactly the successful certificates
    - Entry filenames are sanitized (stripping dangerous traversal paths like '../../evil/name')
    """
    payload = {
        "event_name": "Security Masterclass",
        "issuer": "Security Org",
        "issue_date": "2026-10-07",
        "recipients": [
            {"name": "../../evil/traversal_name", "email": "evil@example.com"},
            {"name": "Safe Regular User", "email": "safe@example.com"},
        ],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    zip_res = client.get(f"/jobs/{job_id}/download")
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"

    # Verify zip integrity and contents
    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
        namelist = zf.namelist()
        assert len(namelist) == 2
        for name in namelist:
            # Traversal characters must be stripped
            assert ".." not in name
            assert "/" not in name
            assert "\\" not in name
            assert name.endswith(".pdf")

        assert any("eviltraversal_name" in name for name in namelist)
        assert any("Safe Regular User" in name for name in namelist)


def test_job_zip_download_no_successful_certificates_returns_409(client):
    """If a job has 0 successful certificates (e.g. all failed validation), return 409."""
    payload = {
        "event_name": "All Invalid",
        "issuer": "Issuer",
        "issue_date": "2026-10-07",
        "recipients": [{"name": "   ", "email": "bad@example.com"}],
    }
    create_res = client.post("/jobs", json=payload)
    job_id = create_res.json()["id"]

    zip_res = client.get(f"/jobs/{job_id}/download")
    assert zip_res.status_code == 409
    assert "no successful certificates" in zip_res.json()["detail"].lower()
