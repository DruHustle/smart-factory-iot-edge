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

## Load Code Onto Devices

### ESP32 WROVER (flash firmware)

1. Connect the ESP32 board to your computer with USB.
2. Create board config:

```bash
cd esp32-wrover
cp include/config.example.h include/config.h
# edit include/config.h with Wi-Fi and MQTT settings
```

3. Build and upload firmware:

```bash
pio run -t upload
```

4. Verify boot logs:

```bash
pio device monitor
```

### Raspberry Pi (deploy gateway)

1. Copy code to the device:

```bash
rsync -av --delete ./ raspberrypi@<PI_IP>:/opt/smart-factory-iot-edge/
```

2. SSH into the Pi and install runtime:

```bash
ssh raspberrypi@<PI_IP>
cd /opt/smart-factory-iot-edge/raspberry-pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with device and broker settings
```

3. Run once interactively:

```bash
python src/sensor_gateway.py
```

4. Enable startup service:

```bash
sudo cp systemd/smart-factory-edge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smart-factory-edge
sudo systemctl restart smart-factory-edge
sudo systemctl status smart-factory-edge
```

## Security Notes

- Use TLS-enabled MQTT in production.
- Rotate credentials and avoid hardcoding secrets in firmware.
- Restrict topic ACLs per device.
