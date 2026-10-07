import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import OUTPUT_DIR
from app.database import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.services.pdf import generate_certificate_pdf

logger = logging.getLogger(__name__)


def process_job(job_id: str) -> None:
    """
    Background worker function that processes pending certificates for a job.

    BACKGROUND TASKS TRADE-OFF NOTE:
    FastAPI's BackgroundTasks is lightweight and requires zero extra infrastructure
    (no Redis, RabbitMQ, or Celery workers). However, tasks execute inside the same
    application process:
    - If the server crashes or restarts, in-flight jobs are interrupted and lost.
    - Tasks do not scale independently across multiple worker nodes.
    In a distributed production environment, a persistent task queue like Celery or RQ
    backed by Redis/PostgreSQL would be preferred for durability and rate-limiting.

    DATABASE SESSION HANDLING:
    This function MUST instantiate and manage its own database session using SessionLocal.
    The session from the originating HTTP request is closed as soon as the HTTP 202 response
    is returned to the client. Attempting to share that request session would cause
    detached instance errors or access to a closed connection.
    """
    db = SessionLocal()
    try:
        # 1. Fetch job record
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.status != JobStatus.PENDING:
            # Job doesn't exist or is already being/been processed (idempotency safeguard)
            return

        # 2. Transition job state to 'processing'
        job.status = JobStatus.PROCESSING
        db.commit()

        # 3. Retrieve only certificates awaiting generation
        pending_certs = (
            db.query(Certificate)
            .filter(
                Certificate.job_id == job_id,
                Certificate.status == CertificateStatus.PENDING,
            )
            .all()
        )

        for cert in pending_certs:
            # File named by certificate UUID to avoid path traversal, special characters, or name collisions
            cert_output_path = Path(OUTPUT_DIR) / str(job_id) / f"{cert.id}.pdf"

            try:
                generate_certificate_pdf(
                    recipient_name=cert.recipient_name,
                    event_name=job.event_name,
                    issuer=job.issuer,
                    issue_date=job.issue_date,
                    output_path=cert_output_path,
                )
                cert.status = CertificateStatus.SUCCESS
                cert.file_path = str(cert_output_path)
                cert.error_message = None
                job.succeeded += 1
            except Exception as exc:
                logger.warning(
                    "Certificate generation failed for recipient %s in job %s: %s",
                    cert.recipient_name,
                    job_id,
                    exc,
                )
                cert.status = CertificateStatus.FAILED
                cert.error_message = f"PDF generation error: {str(exc)}"
                job.failed += 1

            # COMMIT PER CERTIFICATE:
            # Persist each individual result immediately so that clients polling
            # GET /jobs/{job_id} observe real-time progress counters advancing.
            db.commit()

        # 4. Determine final job state
        # Note: job.failed includes both initial validation failures and any PDF generation failures
        if job.succeeded == 0:
            job.status = JobStatus.FAILED
        elif job.failed > 0:
            job.status = JobStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = JobStatus.COMPLETED

        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        logger.exception("Fatal unexpected error during background processing of job %s: %s", job_id, exc)
        try:
            db.rollback()
            # Attempt to set job to failed state so it is never stuck in 'processing'
            failed_job = db.query(Job).filter(Job.id == job_id).first()
            if failed_job and failed_job.status == JobStatus.PROCESSING:
                failed_job.status = JobStatus.FAILED
                failed_job.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.exception("Failed to mark job %s as failed after crash", job_id)
    finally:
        db.close()
