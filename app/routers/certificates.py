from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CertificateStatus
from app.services.retrieval import get_certificate_by_id

router = APIRouter(prefix="/certificates", tags=["Certificates"])


@router.get("/{certificate_id}/download")
def download_certificate(
    certificate_id: str,
    db: Session = Depends(get_db),
):
    """
    Download a single generated certificate PDF.

    SECURITY NOTE:
    We strictly serve the file_path recorded in the database by our trusted background worker.
    We NEVER construct the file path using unvetted user input, preventing directory traversal attacks.
    """
    cert = get_certificate_by_id(db, certificate_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate '{certificate_id}' not found",
        )

    if cert.status == CertificateStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Certificate is not ready yet",
        )

    if cert.status == CertificateStatus.FAILED:
        error_info = cert.error_message or "Unknown processing error"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Certificate generation failed: {error_info}",
        )

    # Status is SUCCESS: verify file presence on disk
    if not cert.file_path or not Path(cert.file_path).is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificate file not found",
        )

    safe_download_filename = f"certificate_{cert.id[:8]}.pdf"
    return FileResponse(
        path=cert.file_path,
        media_type="application/pdf",
        filename=safe_download_filename,
    )
