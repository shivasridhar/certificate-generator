import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import get_db
from app.models import CertificateStatus, JobStatus
from app.schemas import CertificateOut, JobCreate, JobDetailOut, JobOut
from app.services.jobs import create_job
from app.services.processing import process_job
from app.services.retrieval import (
    create_job_zip_archive,
    get_job_by_id,
    list_job_certificates,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def cleanup_file(file_path: str) -> None:
    """Removes a temporary file after the response has finished streaming."""
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except OSError:
        pass


@router.post("", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_job_endpoint(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a bulk certificate generation job.
    
    Validates payload structure and per-recipient data, saves initial job
    and certificate records, schedules background processing for valid recipients,
    and returns HTTP 202 Accepted.
    """
    job = create_job(db=db, payload=payload)

    # Only enqueue background task if there are valid recipients awaiting generation.
    # If all recipients failed validation upfront, the job is already marked as 'failed'.
    if job.status == JobStatus.PENDING:
        background_tasks.add_task(process_job, job.id)

    return job


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job_endpoint(
    job_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieve job metadata, aggregate progress percent, and all individual certificates.
    """
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return job


@router.get("/{job_id}/certificates", response_model=list[CertificateOut])
def list_certificates_endpoint(
    job_id: str,
    status_filter: Optional[CertificateStatus] = Query(
        None,
        alias="status",
        description="Filter by certificate status (pending, success, failed)",
    ),
    limit: int = Query(100, ge=1, le=500, description="Max certificates to return (1-500)"),
    offset: int = Query(0, ge=0, description="Number of certificates to skip"),
    db: Session = Depends(get_db),
):
    """
    List certificates for a given job with optional status filtering and pagination.
    Ordered deterministically by created_at then id.
    """
    certificates = list_job_certificates(
        db=db,
        job_id=job_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    if certificates is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return certificates


@router.get("/{job_id}/download")
def download_job_certificates_zip(
    job_id: str,
    db: Session = Depends(get_db),
):
    """
    Download all successfully generated certificates for a job as a single ZIP archive.
    
    Builds the ZIP on disk in a temporary file and unlinks it after transmission completes.
    """
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    # Collect successful certificates
    successful_certs = [c for c in job.certificates if c.status == CertificateStatus.SUCCESS]
    if not successful_certs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job has no successful certificates available for download",
        )

    temp_zip_path = create_job_zip_archive(successful_certs)

    safe_zip_filename = f"certificates_job_{job_id[:8]}.zip"
    return FileResponse(
        path=temp_zip_path,
        media_type="application/zip",
        filename=safe_zip_filename,
        background=BackgroundTask(cleanup_file, temp_zip_path),
    )
