# ADA031 V4 robotic-arm firmware

This folder contains the Arduino Uno firmware that runs on the Adeept ADA031 V4 arm controller. The Raspberry Pi gateway code that communicates with it lives under `raspberry-pi/`.

## Contents

- `AdeeptArmConnected.ino` controls five servos, handles the ArmBoard button and OLED, accepts the allowlisted serial commands, and emits JSON telemetry.
- `calibration-points.json` records the user-confirmed Point A and Point B poses compiled into the sketch.
- `platformio.ini` defines an Arduino Uno PlatformIO build and its library dependencies.

## Build and upload

Secure the arm and disconnect the separate servo supply before uploading. Uploading or opening the serial port resets the controller, and startup commands all five axes to 90 degrees.

```bash
cd robotic-arm
pio run
pio device list
pio run -t upload --upload-port /dev/cu.usbserial-XXXX
pio device monitor --baud 9600
```

On Linux, use the stable device path when available, such as `/dev/serial/by-id/...`. Close the serial monitor before starting the Raspberry Pi gateway because only one process can own the port.

See [`../docs/ada031-integration.md`](../docs/ada031-integration.md) for protocol details, commissioning steps, limitations, and safety requirements. This educational arm and its software controls are not safety-rated.
