import re

from celery import Celery
from celery.schedules import timedelta

from app.config import settings

celery_app = Celery(
    "rtl_sdr",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-enabled-connectors": {
            "task": "dispatch_enabled_connectors",
            # Workers run for 60 s; fire every 90 s so they finish before the next wave.
            "schedule": timedelta(seconds=90),
        },
    },
)


@celery_app.task(name="dispatch_enabled_connectors")
def dispatch_enabled_connectors():
    """Query all enabled connectors and dispatch a pull task for each one.

    Uses psycopg2 (sync) because Celery tasks are synchronous.
    The DATABASE_URL may use the asyncpg driver prefix; we swap it for the
    psycopg2-compatible postgresql:// scheme before connecting.
    """
    import psycopg2

    db_url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", settings.DATABASE_URL)
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, protocol FROM connectors WHERE enabled = TRUE")
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    for connector_id, protocol in rows:
        trigger_pull.delay(str(connector_id), protocol)

    return {"dispatched": len(rows)}


@celery_app.task(name="trigger_pull")
def trigger_pull(connector_id: str, protocol: str):
    """Dispatch pull task based on protocol."""
    if protocol == "rtl433":
        from app.workers.rtl_433_worker import run_rtl_433
        run_rtl_433(connector_id)
    elif protocol == "adsb":
        from app.workers.dump1090_worker import run_dump1090
        run_dump1090(connector_id)
    elif protocol == "noaa":
        from app.workers.noaa_worker import run_noaa_apt
        run_noaa_apt(connector_id)
    elif protocol == "fm":
        from app.workers.rtl_fm_worker import run_rtl_fm_rds
        run_rtl_fm_rds(connector_id)
    else:
        return {"error": f"Unknown protocol: {protocol}"}
    return {"status": "completed", "connector_id": connector_id}
