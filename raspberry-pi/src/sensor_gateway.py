import json
import signal
import sys
import time
from datetime import datetime, timezone
from threading import Event, Thread

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from config import load_settings

try:
    import serial  # type: ignore
except Exception:  # pragma: no cover
    serial = None


STOP = Event()


def telemetry_topic(site_id: str, line_id: str, device_id: str) -> str:
    return f"factory/{site_id}/{line_id}/{device_id}/telemetry"


def heartbeat_topic(site_id: str, line_id: str, device_id: str) -> str:
    return f"factory/{site_id}/{line_id}/{device_id}/heartbeat"


def command_topic(site_id: str, line_id: str, device_id: str) -> str:
    return f"factory/{site_id}/{line_id}/{device_id}/commands"


def make_mqtt_client(settings):
    client = mqtt.Client(client_id=settings.mqtt_client_id, clean_session=True)
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if settings.mqtt_use_tls:
        client.tls_set()

    def on_connect(_client, _userdata, _flags, rc):
        if rc == 0:
            print("[MQTT] connected")
            _client.subscribe(command_topic(settings.site_id, settings.line_id, settings.device_id))
        else:
            print(f"[MQTT] connect failed rc={rc}")

    def on_message(_client, _userdata, msg):
        payload = msg.payload.decode("utf-8", errors="ignore")
        print(f"[MQTT] command on {msg.topic}: {payload}")

    client.on_connect = on_connect
    client.on_message = on_message
    return client


def parse_serial_line(line: str) -> dict:
    # Expected JSON line from MCU, e.g. {"temperature":24.5,"humidity":56.2,"power":120.1}
    record = json.loads(line)
    if "timestamp" not in record:
        record["timestamp"] = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return record


def serial_reader(settings, publish_fn):
    if not settings.serial_enabled:
        return
    if serial is None:
        print("[SERIAL] pyserial unavailable; serial ingest disabled")
        return

    try:
        ser = serial.Serial(settings.serial_port, settings.serial_baud, timeout=1)
        print(f"[SERIAL] listening on {settings.serial_port} @ {settings.serial_baud}")
    except Exception as exc:
        print(f"[SERIAL] failed to open port: {exc}")
        return

    while not STOP.is_set():
        try:
            raw = ser.readline().decode("utf-8", errors="ignore").strip()
            if not raw:
                continue
            data = parse_serial_line(raw)
            publish_fn(data)
        except Exception as exc:
            print(f"[SERIAL] parse error: {exc}")


def heartbeat_loop(settings, client):
    while not STOP.is_set():
        payload = {
            "deviceId": settings.device_id,
            "timestamp": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
            "status": "online",
        }
        client.publish(heartbeat_topic(settings.site_id, settings.line_id, settings.device_id), json.dumps(payload), qos=1)
        STOP.wait(settings.publish_interval_seconds)


def main():
    load_dotenv()
    settings = load_settings()
    client = make_mqtt_client(settings)

    def publish_telemetry(data: dict):
        payload = {
            "deviceId": settings.device_id,
            "timestamp": data.get("timestamp", int(time.time() * 1000)),
            "temperature": data.get("temperature"),
            "humidity": data.get("humidity"),
            "vibration": data.get("vibration"),
            "power": data.get("power"),
            "pressure": data.get("pressure"),
            "rpm": data.get("rpm"),
        }
        topic = telemetry_topic(settings.site_id, settings.line_id, settings.device_id)
        client.publish(topic, json.dumps(payload), qos=1)
        print(f"[MQTT] telemetry -> {topic}: {payload}")

    def sig_handler(_sig, _frame):
        STOP.set()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    client.loop_start()

    serial_thread = Thread(target=serial_reader, args=(settings, publish_telemetry), daemon=True)
    serial_thread.start()

    hb_thread = Thread(target=heartbeat_loop, args=(settings, client), daemon=True)
    hb_thread.start()

    print("[EDGE] gateway started")

    while not STOP.is_set():
        # If serial ingest is disabled, publish synthetic telemetry for smoke tests.
        if not settings.serial_enabled:
            synthetic = {
                "temperature": 24.5,
                "humidity": 55.0,
                "vibration": 0.15,
                "power": 120.0,
                "pressure": 1.2,
                "rpm": 1450,
                "timestamp": int(time.time() * 1000),
            }
            publish_telemetry(synthetic)
        STOP.wait(settings.publish_interval_seconds)

    client.loop_stop()
    client.disconnect()
    print("[EDGE] gateway stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
