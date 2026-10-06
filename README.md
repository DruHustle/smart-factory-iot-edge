# Smart Factory IoT Edge

Raspberry Pi gateway and ESP32 WROVER firmware for industrial telemetry.

Cloud production releases are coordinated from the dashboard repository: a protected dashboard `main` push resolves this repository's `master` branch to an immutable revision, validates the gateway and firmware, deploys one combined backend image to Render, then deploys the separate static frontend artifact to Vercel. Edge quality CI runs on `master`; CI never flashes plant hardware.

## Data path

The Pi polls OPC UA, Modbus TCP/RTU, and serial JSON equipment, exchanges allowlisted control and controller telemetry with commissioned ADA031 V4 arms, and hosts a local MQTT listener for ESP32 WROVER sensors. The Pi validates local sensor identities and telemetry, then forwards it over TLS to CloudAMQP. Eligible native MQTT devices may publish directly to CloudAMQP with their own scoped credentials and topic ACLs. The ADA031 V4 uses USB serial and must use the Pi gateway. The .NET backend consumes both direct and gateway-originated MQTT telemetry and forwards it to the dashboard through a service-token bridge.

## Device guides

- [Raspberry Pi gateway](raspberry-pi/README.md): install, hardened systemd service, TLS, industrial protocol security, mapping, safe code upload, and troubleshooting.
- [ADA031 V4 integration guide](docs/ada031-integration.md): official stock command bytes, USB serial profile, allowlist, startup motion, temporary code clamps, and feedback limitations.
- [ADA031 V4 robotic-arm firmware](robotic-arm/README.md): Arduino Uno controller source, calibrated poses, build, and upload instructions.
- [ESP32 WROVER firmware](esp32-wrover/README.md): configure, build, flash, TLS trust, and broker ACLs.

Production Pi runs as unprivileged `smartfactory`, with secrets under `/etc/smart-factory-iot/`. The Pi hosts Mosquitto for local sensors and uses a dedicated identity for the TLS CloudAMQP telemetry uplink. Backend services use separate scoped CloudAMQP identities for consuming telemetry, publishing gateway commands, and event-bus traffic. Raspberry Pi updates use staged `rsync` without `--delete`, excluding secrets and the virtual environment. ESP32 firmware uses TLS with the Pi broker certificate and unique local credentials. It publishes QoS 1 telemetry to the Pi; the persistent local MQTT session queues messages during short gateway process restarts. Modbus TCP is plaintext in this adapter; keep it on an isolated OT network or authenticated encrypted tunnel.

## Tests and firmware upload

```bash
# From the repository root; install Python dependencies first as described
# in raspberry-pi/README.md.
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s raspberry-pi/tests -v
cd esp32-wrover
cp include/config.example.h include/smart_factory_config.h
# Edit the ignored smart_factory_config.h with the Pi broker TLS and device credentials.
pio run
pio device list
pio run -t upload --upload-port /dev/ttyUSB0  # use the port reported above
pio device monitor
```

On macOS the WROVER upload port is commonly `/dev/cu.usbserial-*`. See the [firmware guide](esp32-wrover/README.md) before wiring the isolated driver inputs or enabling GPIO requests.

Test with a staging broker and bench equipment before a plant rollout.

## Firmware update support

This edge release has no automated OTA/FOTA agent. The ESP-WROVER firmware has no network update receiver and must be built and flashed over USB using PlatformIO. Raspberry Pi software uses the staged, manual `rsync` deployment procedure in [the gateway guide](raspberry-pi/README.md); it is not updated by the dashboard. The ADA031 V4 Uno is programmed over USB with the project's connected firmware (the official stock sketch remains a deliberate legacy option). The dashboard marks firmware delivery unavailable and its legacy records must not be treated as device update evidence.

Do not enable remote firmware delivery until a signed release pipeline, hardware compatibility checks, authenticated device acknowledgements, rollback/recovery behavior, and staged rollout tests are in place.
