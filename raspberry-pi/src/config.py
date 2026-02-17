from dataclasses import dataclass
import os


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    device_id: str
    site_id: str
    line_id: str

    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_use_tls: bool
    mqtt_client_id: str

    serial_enabled: bool
    serial_port: str
    serial_baud: int

    publish_interval_seconds: int

    postgres_enabled: bool
    postgres_url: str


def load_settings() -> Settings:
    return Settings(
        device_id=os.getenv("DEVICE_ID", "pi-edge-01"),
        site_id=os.getenv("SITE_ID", "factory-a"),
        line_id=os.getenv("LINE_ID", "line-1"),
        mqtt_host=os.getenv("MQTT_HOST", "127.0.0.1"),
        mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
        mqtt_username=os.getenv("MQTT_USERNAME", ""),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        mqtt_use_tls=_as_bool(os.getenv("MQTT_USE_TLS"), False),
        mqtt_client_id=os.getenv("MQTT_CLIENT_ID", "pi-edge-01"),
        serial_enabled=_as_bool(os.getenv("SERIAL_ENABLED"), True),
        serial_port=os.getenv("SERIAL_PORT", "/dev/ttyUSB0"),
        serial_baud=int(os.getenv("SERIAL_BAUD", "115200")),
        publish_interval_seconds=int(os.getenv("PUBLISH_INTERVAL_SECONDS", "5")),
        postgres_enabled=_as_bool(os.getenv("POSTGRES_ENABLED"), False),
        postgres_url=os.getenv("POSTGRES_URL", ""),
    )
