import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import connectors, data, audio, scheduler, device
from app.db.database import engine, Base
from app.ws.live import router as ws_router

# Ensure application-level loggers (app.*) emit INFO and above.
# Uvicorn only configures its own loggers; without this the root logger
# defaults to WARNING and swallows all our pipeline progress messages.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="RTL-SDR Dashboard API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connectors.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(audio.router, prefix="/api")
app.include_router(scheduler.router, prefix="/api")
app.include_router(device.router, prefix="/api")
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
