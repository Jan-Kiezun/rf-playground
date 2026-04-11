from celery import Celery

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
)


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
