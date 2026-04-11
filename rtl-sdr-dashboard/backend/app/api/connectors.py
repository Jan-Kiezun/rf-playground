import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.connector import Connector
from app.workers.celery_app import trigger_pull

router = APIRouter(tags=["connectors"])


class ConnectorCreate(BaseModel):
    name: str
    protocol: str
    frequency_hz: int | None = None
    gain: float | None = None
    sample_rate: int | None = None
    extra_config: dict[str, Any] | None = None


class ConnectorUpdate(BaseModel):
    frequency_hz: int | None = None
    gain: float | None = None
    sample_rate: int | None = None
    extra_config: dict[str, Any] | None = None


@router.get("/connectors")
async def list_connectors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector))
    connectors = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "protocol": c.protocol,
            "enabled": c.enabled,
            "frequency_hz": c.frequency_hz,
            "gain": c.gain,
            "sample_rate": c.sample_rate,
            "extra_config": c.extra_config,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in connectors
    ]


@router.post("/connectors")
async def create_connector(body: ConnectorCreate, db: AsyncSession = Depends(get_db)):
    connector = Connector(**body.model_dump())
    db.add(connector)
    await db.commit()
    await db.refresh(connector)
    return {"id": str(connector.id), "name": connector.name}


@router.post("/connectors/{connector_id}/toggle")
async def toggle_connector(connector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    connector.enabled = not connector.enabled
    await db.commit()
    return {"id": str(connector.id), "enabled": connector.enabled}


@router.put("/connectors/{connector_id}/config")
async def update_connector_config(
    connector_id: uuid.UUID,
    body: ConnectorUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(connector, field, value)
    await db.commit()
    return {"id": str(connector.id), "updated": True}


@router.post("/connectors/{connector_id}/pull")
async def pull_now(connector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    task = trigger_pull.delay(str(connector_id), connector.protocol)
    return {"task_id": task.id, "status": "queued"}
