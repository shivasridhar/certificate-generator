import os
from pathlib import Path
import re
import tempfile
from typing import Optional
import zipfile

from sqlalchemy.orm import Session

from app.models import Certificate, CertificateStatus, Job


def get_job_by_id(db: Session, job_id: str) -> Optional[Job]:
    """Retrieves a Job by UUID from the database, or None if not found."""
    return db.query(Job).filter(Job.id == job_id).first()


def list_job_certificates(
    db: Session,
    job_id: str,
    status_filter: Optional[CertificateStatus] = None,
    limit: int = 100,
    offset: int = 0,
) -> Optional[list[Certificate]]:
    """
    Retrieves paginated certificates for a specific job.

    Returns None if the job itself does not exist, enabling the caller to return a 404.
    Results are ordered deterministically by created_at then id to provide stable paging.
    """
    job = get_job_by_id(db, job_id)
    if not job:
        return None

    query = db.query(Certificate).filter(Certificate.job_id == job_id)
    if status_filter:
        query = query.filter(Certificate.status == status_filter)

    # Stable pagination ordering: created_at, then unique id
    return (
        query.order_by(Certificate.created_at.asc(), Certificate.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_certificate_by_id(db: Session, certificate_id: str) -> Optional[Certificate]:
    """Retrieves an individual Certificate by UUID, or None if not found."""
    return db.query(Certificate).filter(Certificate.id == certificate_id).first()


def sanitize_filename_part(name: str) -> str:
    """
    Sanitizes a string to contain only safe filename characters:
    alphanumerics, spaces, dashes, and underscores.
    Falls back to 'certificate' if the result is empty.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9 _-]", "", name).strip()
    return cleaned if cleaned else "certificate"


def create_job_zip_archive(successful_certs: list[Certificate]) -> str:
    """
    Creates a ZIP archive containing all available successful certificate PDFs.

    DESIGN REASONING & OPTIMIZATION NOTES:
    1. Beyond Required Endpoints: Providing a bulk ZIP download is a practical enhancement
       allowing issuers to download all generated certificates in one go without making
       hundreds of individual HTTP calls.
    2. Temp File on Disk vs Memory: Writing the archive to a temporary file on disk rather
       than assembling it in RAM (e.g. io.BytesIO) avoids memory spikes and out-of-memory
       (OOM) crashes when packaging hundreds of PDFs.
    3. Safe Filenames: Each archive entry is formatted as:
       '<sanitized_name>_<first_8_chars_of_cert_id>.pdf'
       This protects against directory traversal characters (e.g., '../../') while keeping
       files easily identifiable by the recipient's name.
    4. Missing File Resilience: If an individual PDF was accidentally deleted from the filesystem,
       it is gracefully skipped rather than aborting the entire ZIP archive creation.

    Returns:
        The absolute filesystem path of the generated temporary ZIP file.
    """
    # Create an unlinked temp file path
    # On Windows, we must close the NamedTemporaryFile handle before opening it with zipfile!
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name
    temp_zip.close()

    try:
        with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for cert in successful_certs:
                if not cert.file_path:
                    continue

                pdf_path = Path(cert.file_path)
                if not pdf_path.is_file():
                    # Gracefully skip missing files without crashing the overall archive
                    continue

                safe_name = sanitize_filename_part(cert.recipient_name)
                archive_filename = f"{safe_name}_{cert.id[:8]}.pdf"
                zf.write(pdf_path, arcname=archive_filename)

        return temp_zip_path

    except Exception:
        # Clean up temp file immediately if writing failed
        if os.path.exists(temp_zip_path):
            try:
                os.unlink(temp_zip_path)
            except OSError:
                pass
        raise
