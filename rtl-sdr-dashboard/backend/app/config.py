from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://sdr:changeme@postgres:5432/sdrdb"
    REDIS_URL: str = "redis://redis:6379/0"
    RTL_SDR_DEVICE_INDEX: int = 0
    RTL_SDR_GAIN: str = "auto"
    HLS_OUTPUT_DIR: str = "/tmp/hls"
    LASTFM_API_KEY: str = ""
    MUSICBRAINZ_USER_AGENT: str = "rtl-sdr-dashboard/1.0"

    class Config:
        env_file = ".env"


settings = Settings()
