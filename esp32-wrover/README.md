# ESP32 WROVER Firmware

PlatformIO-based firmware for ESP32 WROVER devices.

## Features

- Wi-Fi connection
- MQTT telemetry publish
- MQTT command subscribe
- Heartbeat publish
- Simple command handler (`reboot`)

## Requirements

1. VS Code + PlatformIO extension (or `pio` CLI)
2. ESP32 WROVER board and USB cable
3. Reachable MQTT broker

## Setup

1. Create runtime config:

```bash
cp include/config.example.h include/config.h
# edit include/config.h
```

2. Build firmware:

```bash
pio run
```

3. Flash board:

```bash
pio run -t upload
```

4. Monitor serial output:

```bash
pio device monitor
```

## MQTT Topics

- Telemetry publish: `factory/{site}/{line}/{deviceId}/telemetry`
- Heartbeat publish: `factory/{site}/{line}/{deviceId}/heartbeat`
- Command subscribe: `factory/{site}/{line}/{deviceId}/commands`

## Command Payload Example

```json
{"action":"reboot"}
```

## Production Guidance

- Move credentials to secure provisioning flow.
- Use TLS-enabled MQTT listener and per-device credentials.
- Add OTA update support (ArduinoOTA/HTTPS) if required by your rollout plan.
