"""Settings from environment variables (see deploy/docker-compose.yml)."""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "postgresql://tf01:tf01@localhost:5432/tf01"))
    mqtt_host: str = field(default_factory=lambda: os.environ.get("MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(os.environ.get("MQTT_PORT", "1883")))
    mqtt_username: str | None = field(default_factory=lambda: os.environ.get("MQTT_USERNAME"))
    mqtt_password: str | None = field(default_factory=lambda: os.environ.get("MQTT_PASSWORD"))
    site_prefix: str = field(default_factory=lambda: os.environ.get("SITE_PREFIX", "tf01"))
    auth_secret: str = field(default_factory=lambda: os.environ.get("AUTH_SECRET", "dev-secret-change-me"))
    token_ttl_s: int = field(default_factory=lambda: int(os.environ.get("TOKEN_TTL_S", str(12 * 3600))))
    admin_username: str = field(default_factory=lambda: os.environ.get("ADMIN_USERNAME", "admin"))
    admin_password: str | None = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD"))
    offline_check_s: float = field(default_factory=lambda: float(os.environ.get("OFFLINE_CHECK_S", "15")))
    # Set to 0 to run the API without the MQTT ingest/engine loops (tests).
    run_background: bool = field(default_factory=lambda: os.environ.get("RUN_BACKGROUND", "1") == "1")
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))


settings = Settings()
