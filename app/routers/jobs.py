from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import JobCreate, JobOut
from app.services.jobs import create_job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_job_endpoint(
    payload: JobCreate,
    db: Session = Depends(get_db),
):
    """
    Submit a bulk certificate generation job.
    
    Validates payload structure and per-recipient data, saves initial job
    and certificate records, and returns HTTP 202 Accepted.
    
    All business logic is delegated to the service layer.
    """
    return create_job(db=db, payload=payload)
