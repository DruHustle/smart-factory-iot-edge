#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ESPmDNS.h>
#include <MqttClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <math.h>
#include <time.h>
#include <sys/time.h>

#if __has_include("smart_factory_config.h")
#include "smart_factory_config.h"
#elif defined(SMART_FACTORY_COMPILE_CHECK)
// CI verifies the firmware with documented placeholder values. Normal builds
// still fail closed until the operator creates the ignored private config.
#include "config.example.h"
#else
#error "Copy include/config.example.h to include/smart_factory_config.h and commission Wi-Fi, MQTT, and CA settings before building"
#endif
#ifndef DHT11_DATA_PIN
#define DHT11_DATA_PIN 32
#endif
#ifndef USER_BUTTON_PIN
#define USER_BUTTON_PIN 21
#endif
#ifndef CONTROL_GPIO_PIN_1
#define CONTROL_GPIO_PIN_1 18
#endif
#ifndef CONTROL_GPIO_PIN_2
#define CONTROL_GPIO_PIN_2 19
#endif
#ifndef CONTROL_GPIO_SAFE_LEVEL
#define CONTROL_GPIO_SAFE_LEVEL 0
#endif
#ifndef CONTROL_GPIO_MAX_HOLD_MS
#define CONTROL_GPIO_MAX_HOLD_MS 2000
#endif
#ifndef MQTT_USE_TLS
#define MQTT_USE_TLS 1
#endif
#if MQTT_USE_TLS && !defined(MQTT_ROOT_CA_CERT_CONFIGURED)
#error "MQTT TLS is on by default; configure the Pi gateway CA in smart_factory_config.h or explicitly select an isolated plaintext bench broker"
#endif

bool mdnsStarted = false;

bool resolveMdnsHostname(const char* hostname, IPAddress& address) {
  if (hostname == nullptr) return false;

  String query(hostname);
  if (query.endsWith(".local")) query.remove(query.length() - 6);
  if (query.isEmpty()) return false;

  address = MDNS.queryHost(query, 2000);
  return address[0] != 0 || address[1] != 0 || address[2] != 0 || address[3] != 0;
}

#if MQTT_USE_TLS
// ArduinoMqttClient calls Client::connect(host, port). Resolve .local names
// through mDNS, then pass the original name into TLS for SNI and SAN checks.
class MdnsAwareSecureClient : public WiFiClientSecure {
 public:
  int connect(const char* host, uint16_t port) override {
    if (host == nullptr || !String(host).endsWith(".local")) {
      return WiFiClientSecure::connect(host, port);
    }

    IPAddress address;
    if (!resolveMdnsHostname(host, address)) {
      Serial.printf("[mDNS] Could not resolve MQTT host %s\n", host);
      return 0;
    }

    Serial.printf("[mDNS] %s resolved to %s\n", host, address.toString().c_str());
    return WiFiClientSecure::connect(address, port, host, MQTT_ROOT_CA_CERT, nullptr, nullptr);
  }
};

MdnsAwareSecureClient secureWifiClient;
MqttClient mqttClient(secureWifiClient);
#else
WiFiClient plainWifiClient;
MqttClient mqttClient(plainWifiClient);
#endif

DHT dht11Sensor(DHT11_DATA_PIN, DHT11);

unsigned long lastPublishMs = 0;
const unsigned long publishIntervalMs = 5000;
bool clockReady = false;
bool buttonPressed = false;
bool lastRawButtonPressed = false;
unsigned long buttonChangedAtMs = 0;
uint32_t buttonPressCount = 0;
const unsigned long buttonDebounceMs = 40;

// The selected ESP-WROVER-KIT GPIOs are shared with optional board peripherals.
// Keep the compiled allowlist deliberately narrow; changing it requires a
// board-level pinout review, not just a config edit.
static_assert(DHT11_DATA_PIN == 32 || DHT11_DATA_PIN == 33, "DHT11 data pin must use the reviewed ESP-WROVER-KIT GPIO32/GPIO33 header pins");
static_assert(DHT11_DATA_PIN != CONTROL_GPIO_PIN_1 && DHT11_DATA_PIN != CONTROL_GPIO_PIN_2, "DHT11 data pin cannot overlap a control output");
static_assert(USER_BUTTON_PIN == 21, "The reviewed user-button input is GPIO21 on ESP-WROVER-KIT V4.1");
static_assert(USER_BUTTON_PIN != DHT11_DATA_PIN && USER_BUTTON_PIN != CONTROL_GPIO_PIN_1 && USER_BUTTON_PIN != CONTROL_GPIO_PIN_2, "Button, DHT11, and control pins must be distinct");
static_assert(CONTROL_GPIO_PIN_1 == 18 || CONTROL_GPIO_PIN_1 == 19, "Control GPIO 1 must be GPIO18 or GPIO19 on ESP-WROVER-KIT");
static_assert(CONTROL_GPIO_PIN_2 == 18 || CONTROL_GPIO_PIN_2 == 19, "Control GPIO 2 must be GPIO18 or GPIO19 on ESP-WROVER-KIT");
static_assert(CONTROL_GPIO_PIN_1 != CONTROL_GPIO_PIN_2, "Control GPIO pins must be different");
static_assert(CONTROL_GPIO_SAFE_LEVEL == LOW || CONTROL_GPIO_SAFE_LEVEL == HIGH, "CONTROL_GPIO_SAFE_LEVEL must be LOW or HIGH");
static_assert(CONTROL_GPIO_MAX_HOLD_MS > 0 && CONTROL_GPIO_MAX_HOLD_MS <= 2000, "GPIO control pulses must be at most 2000 ms");

struct ControlOutput {
  uint8_t pin;
  bool leased;
  unsigned long resetAtMs;
};

ControlOutput controlOutputs[] = {
  {CONTROL_GPIO_PIN_1, false, 0},
  {CONTROL_GPIO_PIN_2, false, 0},
};

String recentCommandIds[16];
uint8_t nextRecentCommandId = 0;

bool publishQos1(const String& topic, const char* payload, size_t payloadSize);

String topicTelemetry() {
  return String("factory/") + SITE_ID + "/" + LINE_ID + "/" + DEVICE_ID + "/telemetry";
}

String topicHeartbeat() {
  return String("factory/") + SITE_ID + "/" + LINE_ID + "/" + DEVICE_ID + "/heartbeat";
}

String topicCommands() {
  return String("factory/") + SITE_ID + "/" + LINE_ID + "/" + DEVICE_ID + "/commands";
}

String topicControlAck() {
  return String("factory/") + SITE_ID + "/" + LINE_ID + "/" + DEVICE_ID + "/control-ack";
}

uint64_t currentEpochMilliseconds() {
  timeval now;
  gettimeofday(&now, nullptr);
  return static_cast<uint64_t>(now.tv_sec) * 1000ULL + static_cast<uint64_t>(now.tv_usec / 1000);
}

void configureControlOutputs() {
  for (ControlOutput& output : controlOutputs) {
    // Preload the output latch before enabling output mode to reduce startup glitches.
    digitalWrite(output.pin, CONTROL_GPIO_SAFE_LEVEL);
    pinMode(output.pin, OUTPUT);
  }
  pinMode(USER_BUTTON_PIN, INPUT_PULLUP);
}

void pollUserButton() {
  const bool rawPressed = digitalRead(USER_BUTTON_PIN) == LOW;
  const unsigned long now = millis();
  if (rawPressed != lastRawButtonPressed) {
    lastRawButtonPressed = rawPressed;
    buttonChangedAtMs = now;
  }
  if (rawPressed != buttonPressed && now - buttonChangedAtMs >= buttonDebounceMs) {
    buttonPressed = rawPressed;
    if (buttonPressed) {
      buttonPressCount++;
      Serial.printf("[BUTTON] GPIO%u pressed; count=%lu\n", USER_BUTTON_PIN, static_cast<unsigned long>(buttonPressCount));
    } else {
      Serial.printf("[BUTTON] GPIO%u released\n", USER_BUTTON_PIN);
    }
  }
}

void setAllControlOutputsSafe() {
  for (ControlOutput& output : controlOutputs) {
    digitalWrite(output.pin, CONTROL_GPIO_SAFE_LEVEL);
    output.leased = false;
  }
}

void resetExpiredControlOutputs() {
  const unsigned long now = millis();
  for (ControlOutput& output : controlOutputs) {
    if (output.leased && static_cast<long>(now - output.resetAtMs) >= 0) {
      digitalWrite(output.pin, CONTROL_GPIO_SAFE_LEVEL);
      output.leased = false;
      Serial.printf("[GPIO] GPIO%u returned to configured safe level\n", output.pin);
    }
  }
}

bool isConfiguredControlPin(int pin) {
  for (const ControlOutput& output : controlOutputs) {
    if (pin == output.pin) return true;
  }
  return false;
}

bool validCommandId(const String& commandId) {
  if (commandId.length() < 8 || commandId.length() > 64) return false;
  for (size_t i = 0; i < commandId.length(); i++) {
    const char c = commandId[i];
    const bool valid = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
      (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.';
    if (!valid) return false;
  }
  return true;
}

bool wasCommandSeen(const String& commandId) {
  for (const String& recent : recentCommandIds) {
    if (recent == commandId) return true;
  }
  recentCommandIds[nextRecentCommandId] = commandId;
  nextRecentCommandId = (nextRecentCommandId + 1) % (sizeof(recentCommandIds) / sizeof(recentCommandIds[0]));
  return false;
}

void publishControlAck(const String& commandId, const char* status, int pin = -1, int value = -1, const char* reason = nullptr) {
  JsonDocument ack;
  ack["deviceId"] = DEVICE_ID;
  ack["commandId"] = commandId;
  ack["status"] = status;
  ack["timestamp"] = currentEpochMilliseconds();
  if (pin >= 0) ack["pin"] = pin;
  if (value >= 0) ack["value"] = value;
  if (reason) ack["reason"] = reason;

  char payload[256];
  const size_t size = serializeJson(ack, payload, sizeof(payload));
  if (size > 0 && size < sizeof(payload)) publishQos1(topicControlAck(), payload, size);
}

void handleMqttMessage(int messageSize) {
  const String receivedTopic = mqttClient.messageTopic();
  String payload;
  if (messageSize > 0 && messageSize <= 512) payload.reserve(messageSize);
  while (mqttClient.available()) {
    const int next = mqttClient.read();
    if (next < 0) break;
    if (messageSize > 0 && messageSize <= 512) payload += static_cast<char>(next);
  }

  if (receivedTopic != topicCommands()) {
    Serial.printf("[MQTT] Ignored message on unexpected topic %s\n", receivedTopic.c_str());
    return;
  }
  if (messageSize <= 0 || messageSize > 512 || payload.length() != static_cast<unsigned int>(messageSize)) {
    publishControlAck("invalid", "rejected", -1, -1, "invalid_payload_size");
    return;
  }

  JsonDocument command;
  if (deserializeJson(command, payload) || !command.is<JsonObjectConst>() || command.size() != 7) {
    publishControlAck("invalid", "rejected", -1, -1, "invalid_json_or_schema");
    return;
  }

  const char* action = command["action"];
  const char* rawCommandId = command["commandId"];
  const String commandId = rawCommandId ? String(rawCommandId) : String();
  if (!action || String(action) != "set_gpio" || !validCommandId(commandId) ||
      !command["schemaVersion"].is<int>() || command["schemaVersion"].as<int>() != 1 ||
      !command["pin"].is<int>() || !command["value"].is<int>() ||
      !command["holdMs"].is<unsigned int>() || !command["expiresAt"].is<uint64_t>()) {
    publishControlAck(commandId.length() ? commandId : "invalid", "rejected", -1, -1, "invalid_command_fields");
    return;
  }

  const int pin = command["pin"].as<int>();
  const int value = command["value"].as<int>();
  const unsigned int holdMs = command["holdMs"].as<unsigned int>();
  const uint64_t expiresAt = command["expiresAt"].as<uint64_t>();
  if (!clockReady || !isConfiguredControlPin(pin) || (value != LOW && value != HIGH) ||
      holdMs == 0 || holdMs > CONTROL_GPIO_MAX_HOLD_MS) {
    publishControlAck(commandId, "rejected", pin, value, "pin_or_hold_not_allowed");
    return;
  }

  const uint64_t nowEpochMs = currentEpochMilliseconds();
  if (expiresAt <= nowEpochMs || expiresAt > nowEpochMs + 30000ULL) {
    publishControlAck(commandId, "rejected", pin, value, "command_expired_or_too_far_in_future");
    return;
  }
  if (wasCommandSeen(commandId)) {
    publishControlAck(commandId, "duplicate_ignored", pin, value);
    return;
  }

  for (ControlOutput& output : controlOutputs) {
    if (output.pin == pin) {
      digitalWrite(output.pin, value);
      output.leased = value != CONTROL_GPIO_SAFE_LEVEL;
      output.resetAtMs = millis() + min(holdMs, static_cast<unsigned int>(expiresAt - nowEpochMs));
      break;
    }
  }
  publishControlAck(commandId, "applied", pin, value);
  Serial.printf("[GPIO] GPIO%d set to %d for at most %u ms\n", pin, value, holdMs);
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("[WIFI] Connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[WIFI] Connected. IP: %s\n", WiFi.localIP().toString().c_str());
  if (!mdnsStarted) {
    mdnsStarted = MDNS.begin(DEVICE_ID);
    if (mdnsStarted) {
      Serial.printf("[mDNS] responder started as %s.local\n", DEVICE_ID);
    } else {
      Serial.println("[mDNS] responder could not start; .local gateway lookup may fail");
    }
  }
}

void connectMqtt() {
  mqttClient.setId(DEVICE_ID);
  mqttClient.setKeepAliveInterval(60 * 1000);
  mqttClient.setConnectionTimeout(10 * 1000);
  if (String(MQTT_USER).length() > 0) {
    mqttClient.setUsernamePassword(MQTT_USER, MQTT_PASSWORD);
  }

  while (!mqttClient.connected()) {
    Serial.printf("[MQTT] Connecting to Pi gateway %s:%d ...\n", MQTT_HOST, MQTT_PORT);
    if (mqttClient.connect(MQTT_HOST, MQTT_PORT)) {
      Serial.println("[MQTT] Connected to Pi gateway");
      if (!mqttClient.subscribe(topicCommands(), 1)) {
        Serial.println("[MQTT] Command subscription failed; GPIO commands are unavailable");
      }
    } else {
      Serial.printf("[MQTT] Connect failed error=%d\n", mqttClient.connectError());
      delay(2000);
    }
  }
}

bool publishQos1(const String& topic, const char* payload, size_t payloadSize) {
  if (!mqttClient.connected()) return false;
  if (!mqttClient.beginMessage(topic, payloadSize, false, 1, false)) {
    Serial.printf("[MQTT] Could not start QoS 1 publish to %s\n", topic.c_str());
    return false;
  }

  const size_t written = mqttClient.write(reinterpret_cast<const uint8_t*>(payload), payloadSize);
  const int acknowledged = mqttClient.endMessage();
  if (written != payloadSize || acknowledged != 1) {
    Serial.printf("[MQTT] QoS 1 publish was not acknowledged for %s\n", topic.c_str());
    return false;
  }
  return true;
}

void publishTelemetry() {
  if (!clockReady) {
    Serial.println("[TIME] Waiting for UTC clock sync; skipping telemetry");
    return;
  }

  JsonDocument doc;

  // DHT11 values are sampled from the physical sensor; never substitute invented readings.
  const float temperature = dht11Sensor.readTemperature();
  const float humidity = dht11Sensor.readHumidity();
  const bool readingValid = isfinite(temperature) && isfinite(humidity);

  doc["deviceId"] = DEVICE_ID;
  doc["sensorType"] = "DHT11";
  doc["sensorStatus"] = readingValid ? "ok" : "read_error";
  timeval now;
  gettimeofday(&now, nullptr);
  const uint64_t timestampMs = static_cast<uint64_t>(now.tv_sec) * 1000ULL + static_cast<uint64_t>(now.tv_usec / 1000);
  doc["timestamp"] = timestampMs;
  JsonObject signals = doc["assetSignals"].to<JsonObject>();
  signals["buttonPressed"] = buttonPressed ? 1 : 0;
  signals["buttonPressCount"] = buttonPressCount;
  if (readingValid) {
    doc["temperature"] = temperature;
    doc["humidity"] = humidity;
  } else {
    Serial.printf("[DHT11] Read failed on GPIO%u; omitting temperature/humidity values\n", DHT11_DATA_PIN);
  }

  char out[384];
  const size_t size = serializeJson(doc, out, sizeof(out));
  if (size == 0 || size >= sizeof(out)) {
    Serial.println("[MQTT] Telemetry serialization failed or exceeded buffer size");
    return;
  }

  if (publishQos1(topicTelemetry(), out, size)) {
    Serial.printf("[PUB] QoS 1 telemetry acknowledged by Pi broker: %s\n", out);
  }

  JsonDocument hb;
  hb["deviceId"] = DEVICE_ID;
  hb["status"] = "online";
  hb["timestamp"] = timestampMs;
  char hbOut[128];
  const size_t heartbeatSize = serializeJson(hb, hbOut, sizeof(hbOut));
  if (heartbeatSize > 0 && heartbeatSize < sizeof(hbOut)) {
    publishQos1(topicHeartbeat(), hbOut, heartbeatSize);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  dht11Sensor.begin();
  Serial.printf("[DHT11] Sensor initialized on GPIO%u; readings publish every %lu ms\n", DHT11_DATA_PIN, publishIntervalMs);
  configureControlOutputs();
  mqttClient.onMessage(handleMqttMessage);

  connectWifi();
  String resolvedNtpServer;
  const char* ntpServer = NTP_SERVER_1;
  if (String(NTP_SERVER_1).endsWith(".local")) {
    IPAddress ntpAddress;
    while (!resolveMdnsHostname(NTP_SERVER_1, ntpAddress)) {
      Serial.printf("[mDNS] Waiting to resolve NTP host %s\n", NTP_SERVER_1);
      delay(3000);
    }
    resolvedNtpServer = ntpAddress.toString();
    ntpServer = resolvedNtpServer.c_str();
    Serial.printf("[mDNS] NTP host resolved to %s\n", ntpServer);
  }
  configTime(0, 0, ntpServer);
  Serial.println("[TIME] Waiting for Pi gateway time before TLS certificate checks");
  while (time(nullptr) <= 1700000000) delay(500);
  clockReady = true;
#if MQTT_USE_TLS
  secureWifiClient.setCACert(MQTT_ROOT_CA_CERT);
#endif
  connectMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    // Drop any energized output before a potentially long network recovery.
    setAllControlOutputsSafe();
    mqttClient.stop();
    connectWifi();
  }

  if (!mqttClient.connected()) {
    setAllControlOutputsSafe();
    connectMqtt();
  }

  mqttClient.poll();
  pollUserButton();
  resetExpiredControlOutputs();

  if (!clockReady && time(nullptr) > 1700000000) {
    clockReady = true;
    Serial.println("[TIME] UTC clock synchronized");
  }

  const unsigned long now = millis();
  if (now - lastPublishMs >= publishIntervalMs) {
    lastPublishMs = now;
    publishTelemetry();
  }
}
