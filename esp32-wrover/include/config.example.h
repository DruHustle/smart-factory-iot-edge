#pragma once

// Copy to include/smart_factory_config.h, which is intentionally ignored by Git.
// This device connects only to the Raspberry Pi gateway on the OT network.
#define WIFI_SSID "CHANGE_ME"
#define WIFI_PASSWORD "CHANGE_ME"

#define MQTT_HOST "pi-gateway.ot.example"
#define MQTT_PORT 8883
#define MQTT_USE_TLS 1
#define MQTT_USER "esp32-wrover-01"
#define MQTT_PASSWORD "CHANGE_ME_UNIQUE_LOCAL_BROKER_SECRET"

// Paste the broker root CA PEM. Keep certificate validation enabled.
static constexpr char MQTT_ROOT_CA_CERT[] = R"EOF(
-----BEGIN CERTIFICATE-----
REPLACE_WITH_BROKER_ROOT_CA_CERTIFICATE
-----END CERTIFICATE-----
)EOF";
#define MQTT_ROOT_CA_CERT_CONFIGURED 1

#define DEVICE_ID "esp32-wrover-01"
#define SITE_ID "factory-a"
#define LINE_ID "line-1"
#define NTP_SERVER_1 "pi-gateway.ot.example" // Pi chrony serves time to the isolated OT network.

// GPIO18 is a 3.3 V logic output for an isolated driver input, never a direct load.
#define CONTROL_GPIO_PIN_1 18
#define CONTROL_GPIO_SAFE_LEVEL 0
#define CONTROL_GPIO_MAX_HOLD_MS 2000

// Dedicated button-state LED. GPIO19 drives a low-current LED through a resistor.
#define BUTTON_LED_PIN 19

// DHT11 data output; GPIO32 is available on the ESP-WROVER-KIT header.
#define DHT11_DATA_PIN 32
// Momentary push-button input. Wire GPIO21 to GND; firmware enables the internal pull-up.
// GPIO21 is shared with optional LCD/camera/microSD functions, which must remain disconnected.
#define USER_BUTTON_PIN 21
