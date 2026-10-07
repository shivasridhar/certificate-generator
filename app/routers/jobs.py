from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import JobStatus
from app.schemas import JobCreate, JobOut
from app.services.jobs import create_job
from app.services.processing import process_job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


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
