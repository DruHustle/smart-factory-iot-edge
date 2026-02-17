#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include "config.h"

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

unsigned long lastPublishMs = 0;
const unsigned long publishIntervalMs = 5000;

String topicTelemetry() {
  return String("factory/") + SITE_ID + "/" + LINE_ID + "/" + DEVICE_ID + "/telemetry";
}

String topicHeartbeat() {
  return String("factory/") + SITE_ID + "/" + LINE_ID + "/" + DEVICE_ID + "/heartbeat";
}

String topicCommands() {
  return String("factory/") + SITE_ID + "/" + LINE_ID + "/" + DEVICE_ID + "/commands";
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
}

void handleCommand(const String& payload) {
  Serial.printf("[CMD] %s\n", payload.c_str());

  // Example: {"action":"reboot"}
  StaticJsonDocument<128> cmd;
  DeserializationError err = deserializeJson(cmd, payload);
  if (err) return;

  const char* action = cmd["action"] | "";
  if (String(action) == "reboot") {
    Serial.println("[CMD] Rebooting...");
    delay(300);
    ESP.restart();
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String body;
  body.reserve(length);
  for (unsigned int i = 0; i < length; i++) {
    body += static_cast<char>(payload[i]);
  }

  String inTopic(topic);
  if (inTopic == topicCommands()) {
    handleCommand(body);
  }
}

void connectMqtt() {
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);

  while (!mqttClient.connected()) {
    Serial.printf("[MQTT] Connecting to %s:%d ...\n", MQTT_HOST, MQTT_PORT);
    bool ok = false;

    if (String(MQTT_USER).length() > 0) {
      ok = mqttClient.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD);
    } else {
      ok = mqttClient.connect(DEVICE_ID);
    }

    if (ok) {
      Serial.println("[MQTT] Connected");
      mqttClient.subscribe(topicCommands().c_str(), 1);
    } else {
      Serial.printf("[MQTT] Connect failed rc=%d\n", mqttClient.state());
      delay(2000);
    }
  }
}

void publishTelemetry() {
  StaticJsonDocument<256> doc;

  // Replace with real sensor readings
  float temperature = 24.0f + (random(-20, 20) / 10.0f);
  float humidity = 55.0f + (random(-50, 50) / 10.0f);
  float vibration = 0.12f + (random(-5, 5) / 100.0f);
  float power = 120.0f + (random(-50, 50) / 10.0f);
  float pressure = 1.2f + (random(-3, 3) / 10.0f);
  int rpm = 1450 + random(-40, 40);

  doc["deviceId"] = DEVICE_ID;
  doc["timestamp"] = (uint64_t)millis();
  doc["temperature"] = temperature;
  doc["humidity"] = humidity;
  doc["vibration"] = vibration;
  doc["power"] = power;
  doc["pressure"] = pressure;
  doc["rpm"] = rpm;

  char out[256];
  size_t n = serializeJson(doc, out);
  mqttClient.publish(topicTelemetry().c_str(), out, n, false);

  StaticJsonDocument<128> hb;
  hb["deviceId"] = DEVICE_ID;
  hb["status"] = "online";
  hb["timestamp"] = (uint64_t)millis();
  char hbOut[128];
  size_t hbn = serializeJson(hb, hbOut);
  mqttClient.publish(topicHeartbeat().c_str(), hbOut, hbn, false);

  Serial.printf("[PUB] %s\n", out);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  randomSeed(analogRead(0));

  connectWifi();
  connectMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
  }

  if (!mqttClient.connected()) {
    connectMqtt();
  }

  mqttClient.loop();

  unsigned long now = millis();
  if (now - lastPublishMs >= publishIntervalMs) {
    lastPublishMs = now;
    publishTelemetry();
  }
}
