"""
Optional direct PostgreSQL forwarder.
Use only when your architecture requires edge-to-DB writes.
Preferred design is edge -> broker -> backend -> DB.
"""

import json
from datetime import datetime, timezone

from dotenv import load_dotenv
from psycopg import connect

from config import load_settings


def main():
    load_dotenv()
    settings = load_settings()
    if not settings.postgres_enabled:
        print("POSTGRES_ENABLED=false; skipping")
        return

    if not settings.postgres_url:
        raise RuntimeError("POSTGRES_URL is required when POSTGRES_ENABLED=true")

    with connect(settings.postgres_url) as conn:
        with conn.cursor() as cur:
            ts = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
            payload = {
                "deviceId": settings.device_id,
                "temperature": 25.0,
                "humidity": 56.0,
                "vibration": 0.1,
                "power": 118.0,
                "pressure": 1.1,
                "rpm": 1420,
                "timestamp": ts,
            }
            cur.execute(
                """
                insert into sensor_readings
                ("deviceId", temperature, humidity, vibration, power, pressure, rpm, timestamp)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["deviceId"],
                    payload["temperature"],
                    payload["humidity"],
                    payload["vibration"],
                    payload["power"],
                    payload["pressure"],
                    payload["rpm"],
                    payload["timestamp"],
                ),
            )
        conn.commit()
    print("Inserted sample record")
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
