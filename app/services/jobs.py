from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate
from app.services.validation import validate_recipients


def create_job(db: Session, payload: JobCreate) -> Job:
    """
    Creates a new bulk certificate generation job and its associated certificates.
    
    1. Validates each recipient individually (name, email format, duplicates).
    2. Instantiates the Job record with aggregate totals and failure counts.
    3. Bulk creates Certificate records (valid ones as 'pending', invalid ones as 'failed').
    4. If no recipients are valid, marks the Job as 'failed' immediately with completed_at set.
    5. Commits everything in a single database transaction.
    
    Args:
        db: Active SQLAlchemy database session.
        payload: Validated JobCreate payload.
        
    Returns:
        The created Job ORM instance.
    """
    # 1. Run per-recipient validation
    validation_results = validate_recipients(payload.recipients)

    total_count = len(validation_results)
    failed_count = sum(1 for res in validation_results if not res.is_valid)
    all_failed = (failed_count == total_count)

    # If every recipient in the batch failed validation, no certificates can be generated,
    # so we immediately complete the job in a failed state.
    job_status = JobStatus.FAILED if all_failed else JobStatus.PENDING
    completed_at = datetime.now(timezone.utc) if all_failed else None

    # 2. Create the parent Job row
    job = Job(
        event_name=payload.event_name,
        issuer=payload.issuer,
        issue_date=payload.issue_date,
        total=total_count,
        succeeded=0,
        failed=failed_count,
        status=job_status,
        completed_at=completed_at,
    )
    db.add(job)
    # Flush assigns job.id so certificate foreign keys can reference it
    db.flush()

    # 3. Build certificate rows for bulk insertion
    certificates: list[Certificate] = []
    for res in validation_results:
        cert_status = CertificateStatus.PENDING if res.is_valid else CertificateStatus.FAILED
        cert = Certificate(
            job_id=job.id,
            recipient_name=res.recipient.name.strip(),
            recipient_email=res.recipient.email.strip(),
            status=cert_status,
            error_message=res.error if not res.is_valid else None,
        )
        certificates.append(cert)

    # 4. Bulk insert certificates and commit the entire transaction at once
    db.add_all(certificates)
    db.commit()
    db.refresh(job)

    return job
