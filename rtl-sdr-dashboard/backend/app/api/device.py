import asyncio

from fastapi import APIRouter

router = APIRouter(tags=["device"])


@router.get("/device/status")
async def device_status():
    try:
        proc = await asyncio.create_subprocess_exec(
            "rtl_test", "-t",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            return {"connected": False, "error": "rtl_test timed out"}

        output = (stdout + stderr).decode(errors="replace")
        connected = "Found" in output or "Tuner type" in output
        return {
            "connected": connected,
            "output": output[:500],
        }
    except FileNotFoundError:
        return {"connected": False, "error": "rtl_test not found"}
