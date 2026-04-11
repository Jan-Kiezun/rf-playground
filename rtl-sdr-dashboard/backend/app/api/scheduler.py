import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.signal_data import ScheduledJob

router = APIRouter(tags=["scheduler"])


class JobCreate(BaseModel):
    connector_id: uuid.UUID
    cron_expression: str
    enabled: bool = True


@router.get("/schedule")
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScheduledJob))
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "connector_id": str(j.connector_id) if j.connector_id else None,
            "cron_expression": j.cron_expression,
            "enabled": j.enabled,
            "last_run": j.last_run.isoformat() if j.last_run else None,
            "next_run": j.next_run.isoformat() if j.next_run else None,
        }
        for j in jobs
    ]


@router.post("/schedule")
async def create_job(body: JobCreate, db: AsyncSession = Depends(get_db)):
    job = ScheduledJob(**body.model_dump())
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"id": str(job.id)}


@router.delete("/schedule/{job_id}")
async def delete_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.delete(job)
    await db.commit()
    return {"deleted": True}


@router.patch("/schedule/{job_id}/toggle")
async def toggle_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.enabled = not job.enabled
    await db.commit()
    return {"id": str(job.id), "enabled": job.enabled}
