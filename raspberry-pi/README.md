# Raspberry Pi Edge Gateway

Python edge gateway for Smart Factory telemetry.

## Features

- MQTT telemetry publish
- MQTT command subscribe
- Serial ingest from attached MCU (ESP32/other)
- Heartbeat publishing
- Optional PostgreSQL direct forward script

## Requirements

1. Raspberry Pi OS (or Linux)
2. Python 3.10+
3. Network access to MQTT broker
4. Optional USB serial link to MCU

## Setup

1. Create virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure env:

```bash
cp .env.example .env
# edit .env values
```

3. Run gateway:

```bash
python src/sensor_gateway.py
```

## Using Systemd

1. Copy project to `/opt/smart-factory-iot-edge/raspberry-pi`
2. Copy unit file:

```bash
sudo cp systemd/smart-factory-edge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smart-factory-edge
sudo systemctl start smart-factory-edge
sudo systemctl status smart-factory-edge
```

## MQTT Topics

- Telemetry: `factory/{site}/{line}/{deviceId}/telemetry`
- Heartbeat: `factory/{site}/{line}/{deviceId}/heartbeat`
- Commands: `factory/{site}/{line}/{deviceId}/commands`

## Production Guidance

- Enable TLS (`MQTT_USE_TLS=true`) and authenticated broker users.
- Restrict publish/subscribe ACLs by topic.
- Prefer backend-mediated DB writes instead of direct edge-to-Postgres writes.
