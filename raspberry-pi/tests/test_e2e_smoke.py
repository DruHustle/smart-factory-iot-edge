import importlib
import json
import sys
import types
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _purge_modules(*names: str) -> None:
    for name in names:
        sys.modules.pop(name, None)


def _install_dotenv_stub() -> None:
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_mod


class FakeMqttClient:
    def __init__(self):
        self.published = []
        self.connected = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

    def username_pw_set(self, *_args, **_kwargs):
        pass

    def tls_set(self, *_args, **_kwargs):
        pass

    def connect(self, host, port, keepalive=60):
        self.connected = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))

    def subscribe(self, *_args, **_kwargs):
        pass


def _install_paho_stub() -> None:
    client_mod = types.ModuleType("paho.mqtt.client")
    client_mod.Client = lambda *args, **kwargs: FakeMqttClient()

    mqtt_mod = types.ModuleType("paho.mqtt")
    mqtt_mod.client = client_mod

    paho_mod = types.ModuleType("paho")
    paho_mod.mqtt = mqtt_mod

    sys.modules["paho"] = paho_mod
    sys.modules["paho.mqtt"] = mqtt_mod
    sys.modules["paho.mqtt.client"] = client_mod


class OneShotStop:
    def __init__(self):
        self._stopped = False

    def is_set(self):
        return self._stopped

    def set(self):
        self._stopped = True

    def wait(self, _seconds):
        self._stopped = True
        return True


class InlineThread:
    def __init__(self, target=None, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        if self.target is not None:
            self.target(*self.args)


class GatewaySmokeTests(unittest.TestCase):
    def setUp(self):
        _purge_modules("sensor_gateway", "dotenv", "paho", "paho.mqtt", "paho.mqtt.client")
        _install_dotenv_stub()
        _install_paho_stub()

    def _run_gateway_once(self, serial_enabled: bool):
        sensor_gateway = importlib.import_module("sensor_gateway")

        settings = types.SimpleNamespace(
            device_id="pi-edge-01",
            site_id="factory-a",
            line_id="line-1",
            mqtt_host="127.0.0.1",
            mqtt_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_use_tls=False,
            mqtt_client_id="pi-edge-01",
            serial_enabled=serial_enabled,
            serial_port="/dev/ttyUSB0",
            serial_baud=115200,
            publish_interval_seconds=1,
            postgres_enabled=False,
            postgres_url="",
        )

        fake_client = FakeMqttClient()

        sensor_gateway.load_settings = lambda: settings
        sensor_gateway.make_mqtt_client = lambda _settings: fake_client
        sensor_gateway.serial_reader = lambda *_args, **_kwargs: None
        sensor_gateway.heartbeat_loop = lambda *_args, **_kwargs: None
        sensor_gateway.signal.signal = lambda *_args, **_kwargs: None
        sensor_gateway.Thread = InlineThread
        sensor_gateway.STOP = OneShotStop()

        sensor_gateway.main()
        return fake_client, settings, sensor_gateway

    def test_synthetic_telemetry_published_when_serial_disabled(self):
        fake_client, settings, sensor_gateway = self._run_gateway_once(serial_enabled=False)
        telemetry_topic = sensor_gateway.telemetry_topic(settings.site_id, settings.line_id, settings.device_id)
        telemetry_messages = [m for m in fake_client.published if m[0] == telemetry_topic]
        self.assertEqual(len(telemetry_messages), 1)
        payload = json.loads(telemetry_messages[0][1])
        self.assertEqual(payload["deviceId"], settings.device_id)

    def test_synthetic_telemetry_not_published_when_serial_enabled(self):
        fake_client, settings, sensor_gateway = self._run_gateway_once(serial_enabled=True)
        telemetry_topic = sensor_gateway.telemetry_topic(settings.site_id, settings.line_id, settings.device_id)
        telemetry_messages = [m for m in fake_client.published if m[0] == telemetry_topic]
        self.assertEqual(len(telemetry_messages), 0)


class PostgresForwarderSmokeTests(unittest.TestCase):
    def setUp(self):
        _purge_modules("postgres_forwarder", "dotenv", "psycopg")
        _install_dotenv_stub()

    def test_postgres_forwarder_uses_configured_device_id(self):
        captured = {"params": None}

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, _sql, params):
                captured["params"] = params

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return FakeCursor()

            def commit(self):
                pass

        psycopg_mod = types.ModuleType("psycopg")
        psycopg_mod.connect = lambda *_args, **_kwargs: FakeConn()
        sys.modules["psycopg"] = psycopg_mod

        postgres_forwarder = importlib.import_module("postgres_forwarder")

        settings = types.SimpleNamespace(
            device_id="pi-edge-99",
            postgres_enabled=True,
            postgres_url="postgresql://local/test",
        )
        postgres_forwarder.load_settings = lambda: settings

        postgres_forwarder.main()
        self.assertIsNotNone(captured["params"])
        self.assertEqual(captured["params"][0], settings.device_id)


if __name__ == "__main__":
    unittest.main()
