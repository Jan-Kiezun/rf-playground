from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://sdr:changeme@postgres:5432/sdrdb"
    REDIS_URL: str = "redis://redis:6379/0"
    RTL_SDR_DEVICE_INDEX: int = 0
    RTL_SDR_GAIN: str = "auto"
    RTL_TCP_HOST: str = "sdr-tools"
    RTL_TCP_PORT: int = 1234
    RTL_TCP_HEALTH_PORT: int = 8080
    HLS_OUTPUT_DIR: str = "/tmp/hls"
    LASTFM_API_KEY: str = ""
    MUSICBRAINZ_USER_AGENT: str = "rtl-sdr-dashboard/1.0"

    @property
    def rtl_tcp_device(self) -> str:
        """RTL-SDR device string for rtl_fm (double-colon format)."""
        return f"rtl_tcp::{self.RTL_TCP_HOST}:{self.RTL_TCP_PORT}"

    @property
    def rtl_433_device(self) -> str:
        """RTL-SDR device string for rtl_433 (single-colon format)."""
        return f"rtl_tcp:{self.RTL_TCP_HOST}:{self.RTL_TCP_PORT}"

    class Config:
        env_file = ".env"


settings = Settings()
