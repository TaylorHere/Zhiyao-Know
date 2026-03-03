import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.worker import enqueue_job
from models.extract_job import ExtractJob
from schemas.extract import ExtractJobCreateResponse, ExtractJobStatusResponse, ExtractRequest, UsageInfo

router = APIRouter(prefix="/api/v1", tags=["extract"])


@router.post("/extract", response_model=ExtractJobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_extract_job(
    payload: ExtractRequest, session: AsyncSession = Depends(get_session)
):
    job_id = uuid4().hex
    now = datetime.utcnow()
    job = ExtractJob(
        id=job_id,
        status="pending",
        request_json=json.dumps(
            {**payload.model_dump(mode="json"), "trigger_source": "adhoc"}, ensure_ascii=False
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.commit()
    await enqueue_job(job_id)
    return ExtractJobCreateResponse(job_id=job_id, status="pending", created_at=now)


@router.get("/extract/{job_id}", response_model=ExtractJobStatusResponse)
async def get_extract_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await session.get(ExtractJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = json.loads(job.result_json) if job.result_json else None
    usage = None
    if job.usage_json:
        usage = UsageInfo.model_validate(json.loads(job.usage_json))

    return ExtractJobStatusResponse(
        job_id=job.id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        result=result,
        usage=usage,
        error_message=job.error_message,
    )
