import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.signal_data import SignalData, SatImage

router = APIRouter(tags=["data"])


@router.get("/data/{connector_id}")
async def get_connector_data(
    connector_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(SignalData)
        .where(SignalData.connector_id == connector_id)
        .order_by(desc(SignalData.time))
        .offset(offset)
        .limit(page_size)
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "time": r.time.isoformat(),
            "connector_id": str(r.connector_id) if r.connector_id else None,
            "data": r.data,
            "raw_text": r.raw_text,
        }
        for r in rows
    ]


@router.get("/data/latest")
async def get_latest_per_connector(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    subquery = (
        select(SignalData.connector_id, func.max(SignalData.time).label("max_time"))
        .group_by(SignalData.connector_id)
        .subquery()
    )
    result = await db.execute(
        select(SignalData).join(
            subquery,
            (SignalData.connector_id == subquery.c.connector_id)
            & (SignalData.time == subquery.c.max_time),
        )
    )
    rows = result.scalars().all()
    return [
        {
            "connector_id": str(r.connector_id) if r.connector_id else None,
            "time": r.time.isoformat(),
            "data": r.data,
        }
        for r in rows
    ]


@router.get("/images")
async def list_images(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SatImage).order_by(desc(SatImage.captured_at)).limit(100))
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "connector_id": str(r.connector_id) if r.connector_id else None,
            "captured_at": r.captured_at.isoformat(),
            "file_path": r.file_path,
            "pass_metadata": r.pass_metadata,
        }
        for r in rows
    ]


@router.get("/images/{image_id}")
async def get_image(image_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    result = await db.execute(select(SatImage).where(SatImage.id == image_id))
    row = result.scalar_one_or_none()
    if not row or not row.file_path:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(row.file_path)
