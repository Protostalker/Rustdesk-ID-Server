"""Runtime configuration. All values are overridable via environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Where the app's own SQLite database lives (persisted volume in compose).
    app_db_path: str = "/data/companion.sqlite3"

    # Read-only mount of the RustDesk server data directory.
    rustdesk_data_dir: str = "/rustdesk-data"

    # RustDesk OSS database filename (observed at time of writing).
    # If RustDesk changes this, set RUSTDESK_DB_FILENAME in the environment.
    rustdesk_db_filename: str = "db_v2.sqlite3"

    # How often the background sync runs.
    sync_interval_seconds: int = 60

    # Feature flag: allow the UI to attempt to launch the local RustDesk client.
    # Disabled by default because it is environment-dependent.
    launch_rustdesk_enabled: bool = False

    # Live presence polling against hbbs's in-memory peer registry.
    # hbbs_host resolves inside the backend container — on Linux Docker we add
    # host.docker.internal as host-gateway in docker-compose.yml.
    # hbbs_port is the NAT-test TCP port (main RustDesk port minus 1 = 21115).
    # Leave host empty to disable presence polling entirely.
    hbbs_host: str | None = "host.docker.internal"
    hbbs_port: int | None = 21115
    presence_interval_seconds: int = 20
    presence_timeout_seconds: float = 5.0

    # CORS: used only in dev when the frontend is not served through the
    # compose nginx reverse proxy. In compose we keep this locked to same-origin.
    cors_allow_origins: str = "*"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @property
    def rustdesk_db_path(self) -> Path:
        return Path(self.rustdesk_data_dir) / self.rustdesk_db_filename


@lru_cache
def get_settings() -> Settings:
    return Settings()
