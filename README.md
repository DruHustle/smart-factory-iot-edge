# Smart Factory IoT Edge

Edge runtime repository for factory devices.

This repo contains:

1. Raspberry Pi edge gateway code (Python)
2. ESP32 WROVER firmware (PlatformIO/Arduino)

## Architecture

- ESP32 reads local sensors and publishes telemetry to MQTT.
- Raspberry Pi runs as edge gateway and can:
  - ingest telemetry over serial or MQTT
  - publish normalized telemetry to MQTT broker
  - subscribe to command/OTA topics
  - optionally forward data to PostgreSQL
- Cloud/backend services consume MQTT and persist/process data.

## Folder Layout

- `raspberry-pi/`: Python edge gateway for Linux/Raspberry Pi OS
- `esp32-wrover/`: Firmware for ESP32 WROVER boards

## Infrastructure Requirements

1. MQTT broker (RabbitMQ MQTT plugin or Mosquitto)
2. PostgreSQL (optional direct ingest from edge, usually backend owns writes)
3. Network path from edge devices to broker/backend

## Topic Convention

- Telemetry publish: `factory/{site}/{line}/{deviceId}/telemetry`
- Heartbeat publish: `factory/{site}/{line}/{deviceId}/heartbeat`
- Command subscribe: `factory/{site}/{line}/{deviceId}/commands`
- OTA status publish: `factory/{site}/{line}/{deviceId}/ota/status`

## Quick Start

1. Configure and run ESP32 firmware from `esp32-wrover/README.md`.
2. Configure Raspberry Pi gateway from `raspberry-pi/README.md`.
3. Confirm telemetry appears on your broker and backend.

## Security Notes

- Use TLS-enabled MQTT in production.
- Rotate credentials and avoid hardcoding secrets in firmware.
- Restrict topic ACLs per device.
