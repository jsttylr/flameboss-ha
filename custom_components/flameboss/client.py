"""Local client for Flame Boss / EGG Genius controllers.

The controller runs its own small MQTT broker on port 1883 (MQTT 3.1.1, no TLS).
Per Flame Boss's official API docs (https://github.com/flameboss/fb-api-doc),
log in with username "fb" and the device PIN as the password. The controller
publishes JSON "uplinks" on flameboss/<device_id>/send/data and accepts JSON
"downlinks" on flameboss/<device_id>/recv. Every message has a "name" key:

    {"name":"temps","temps":[1072,650,-32767,-32767],"set_temp":1072,"blower":2500}
    {"name":"id","device_id":123456,"hw_id":...,"uid":"..."}
    {"name":"set_temp_limits","min":380,"max":3430}
    {"name":"state","value":"run"}

Temperatures are tenths of a degree Celsius (-32767 = no probe); blower is
hundredths of a percent. Sending {"name":"sync"} asks for every setting and
reading. To change the pit setpoint, send {"name":"set_temp","value":<tenths C>}.

Older firmware used an unauthenticated "direct" mode (GET /switch, then
hex-encoded JSON) as seen in the MIT-licensed OpenBoss project; hex payloads
are still decoded just in case.

This module has no Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import binascii
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .const import DEFAULT_MAX_TEMP_C, DEFAULT_MIN_TEMP_C, DEFAULT_USERNAME, NO_PROBE

_LOGGER = logging.getLogger(__name__)


def decode_temp(raw: Any) -> float | None:
    """Convert a raw temperature (tenths of a degree C) to Celsius."""
    if raw is None or raw == NO_PROBE:
        return None
    try:
        return round(float(raw) / 10.0, 1)
    except (TypeError, ValueError):
        return None


def encode_temp(celsius: float) -> int:
    """Convert Celsius to the controller's tenths-of-a-degree format."""
    return round(float(celsius) * 10.0)


def decode_payload(payload: bytes) -> dict[str, Any] | None:
    """Decode a message from the controller: plain JSON or hex-encoded JSON."""
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if not text.startswith("{"):
        try:
            text = binascii.unhexlify(text).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


_SECRET_KEYS = {"pin", "key", "password", "pass", "psk", "k"}


def _redact(msg: dict[str, Any]) -> dict[str, Any]:
    """Hide the PIN and Wi-Fi passwords before anything is logged."""
    return {k: ("****" if k in _SECRET_KEYS else v) for k, v in msg.items()}


def encode_command(data: dict[str, Any]) -> str:
    """Encode a downlink as compact JSON."""
    return json.dumps(data, separators=(",", ":"))


@dataclass
class FlameBossState:
    """Latest known state of a controller."""

    connected: bool = False
    device_id: int | None = None
    hw_id: int | None = None
    temps: list[float | None] = field(default_factory=list)
    set_temp: float | None = None
    blower: float | None = None
    cook_id: int | None = None
    min_temp: float = DEFAULT_MIN_TEMP_C
    max_temp: float = DEFAULT_MAX_TEMP_C
    run_state: str | None = None
    labels: list[str] = field(default_factory=list)
    pit_alarm: dict[str, Any] = field(default_factory=dict)
    meat_alarms: dict[int, dict[str, Any]] = field(default_factory=dict)
    timer: dict[str, Any] = field(default_factory=dict)
    sound_alarm: bool = False
    wifi_rssi: int | None = None
    dc_input: float | None = None
    device_temp: float | None = None
    versions: dict[str, Any] = field(default_factory=dict)
    last_message: float | None = None
    last_event: str | None = None

    _cook_seen: bool = False

    @property
    def status(self) -> str | None:
        """idle / run / error. EGG Genius never sends "state", so fall back to the cook ID."""
        if self.run_state:
            return self.run_state
        if self.cook_id is not None:
            return "run" if self.cook_id else "idle"
        return None

    @property
    def alarm_active(self) -> bool:
        """True while the controller is sounding any alert."""
        return self.sound_alarm or self.pit_alarm.get("status") == "alerting"

    def apply(self, msg: dict[str, Any]) -> str | None:
        """Apply one uplink. Returns an event name for one-off alerts, else None."""
        name = msg.get("name")
        self.last_message = time.time()
        if name == "temps":
            temps = msg.get("temps")
            if isinstance(temps, list):
                self.temps = [decode_temp(t) for t in temps]
            if "set_temp" in msg:
                self.set_temp = decode_temp(msg["set_temp"])
            if msg.get("blower") is not None:
                try:
                    self.blower = round(float(msg["blower"]) / 100.0, 1)
                except (TypeError, ValueError):
                    pass
            if msg.get("cook_id") is not None:
                self.cook_id = msg["cook_id"]
        elif name == "cook":
            self.cook_id = msg.get("id", self.cook_id)
            self._cook_seen = True
        elif name == "set_temp" and "value" in msg:
            self.set_temp = decode_temp(msg["value"])
        elif name == "id":
            if msg.get("device_id") is not None:
                self.device_id = int(msg["device_id"])
            if msg.get("hw_id") is not None:
                self.hw_id = msg["hw_id"]
        elif name == "set_temp_limits":
            lo, hi = decode_temp(msg.get("min")), decode_temp(msg.get("max"))
            if lo is not None:
                self.min_temp = lo
            if hi is not None:
                self.max_temp = hi
        elif name == "state":
            self.run_state = msg.get("value")
        elif name == "labels" and isinstance(msg.get("values"), list):
            self.labels = [str(v) for v in msg["values"]]
        elif name == "pit_alarm":
            self.pit_alarm = {k: v for k, v in msg.items() if k != "name"}
        elif name == "meat_alarm" and msg.get("sensor") is not None:
            self.meat_alarms[int(msg["sensor"])] = {k: v for k, v in msg.items() if k != "name"}
        elif name == "timer":
            self.timer = {k: v for k, v in msg.items() if k != "name"}
        elif name == "sound":
            self.sound_alarm = msg.get("status") == "alarm"
        elif name == "wifi_cx":
            self.wifi_rssi = msg.get("rssi", self.wifi_rssi)
        elif name == "dc_input" and msg.get("value") is not None:
            self.dc_input = round(float(msg["value"]) / 10.0, 1)
        elif name == "device_temp":
            self.device_temp = decode_temp(msg.get("value"))
        elif name in ("wifi", "ip", "dns", "ntp", "mqtt", "pid", "cal_user", "adc_cal",
                      "log_level", "wifi_module", "local_access", "overtemp_limits",
                      "time", "synced"):
            pass  # settings we don't expose (some contain Wi-Fi passwords; never stored)
        elif name == "versions":
            self.versions = {k: v for k, v in msg.items() if k != "name"}
        elif name in (
            "meat_alarm_triggered",
            "pit_alarm_triggered",
            "pit_alarm_active",
            "vent_advice",
            "probe_overtemp",
            "device_overtemp",
        ):
            self.last_event = name
            return name
        else:
            _LOGGER.debug("Unhandled Flame Boss message: %s", _redact(msg))
        return None


def _new_mqtt_client(client_id: str) -> mqtt.Client:
    """Create a paho client that works with paho-mqtt 1.x and 2.x."""
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
    return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)


class FlameBossClient:
    """Keeps one MQTT connection to a controller and tracks its state."""

    # Ping every 5 s like the official app; the controller's own MQTT timeout is 10 s.
    KEEPALIVE = 5

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        host: str,
        port: int,
        pin: str | None = None,
        device_id: int | None = None,
        username: str | None = None,
        on_update: Callable[[FlameBossState], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._loop = loop
        self.host = host
        self.port = port
        self._username = username or DEFAULT_USERNAME
        self.pin = str(pin) if pin not in (None, "") else None
        self._on_update = on_update
        self._on_event = on_event
        self.state = FlameBossState(device_id=device_id)
        self._client: mqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._disconnected = asyncio.Event()
        self._connected_once = asyncio.Event()
        self._first_attempt = asyncio.Event()
        self._last_connected: float | None = None
        self._stopping = False
        self.last_error: str | None = None
        self.auth_failed = False

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Start connecting in the background, reconnecting as needed."""
        self._stopping = False
        self._task = self._loop.create_task(self._run())

    async def stop(self) -> None:
        """Disconnect and stop reconnecting."""
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._loop.run_in_executor(None, self._teardown)

    async def wait_connected(self, timeout: float) -> bool:
        """Wait until the first successful connection, or give up."""
        try:
            await asyncio.wait_for(self._first_attempt.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return self._connected_once.is_set()

    async def wait_for_device_id(self, timeout: float) -> int | None:
        """Wait until we know the controller's device ID."""
        end = self._loop.time() + timeout
        while self.state.device_id is None and self._loop.time() < end:
            await asyncio.sleep(0.2)
        return self.state.device_id

    async def _run(self) -> None:
        delay = 5
        while not self._stopping:
            self._disconnected.clear()
            try:
                await self._loop.run_in_executor(None, self._connect)
                await self._disconnected.wait()
                if self.state.connected:
                    # Some controllers end every session after ~10 s; reconnect quickly.
                    delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                self.last_error = str(err)
                self._loop.call_soon(self._first_attempt.set)
                _LOGGER.debug("Flame Boss %s connect failed: %s", self.host, err)
            await self._loop.run_in_executor(None, self._teardown)
            self._set_connected(False)
            if self._stopping:
                break
            await asyncio.sleep(delay)
            delay = min(max(delay * 2, 5), 60)

    # ---- paho side (runs in executor / paho thread) ----------------------

    def _connect(self) -> None:
        client = _new_mqtt_client(f"ha-flameboss-{uuid.uuid4().hex[:8]}")
        client.enable_logger(logging.getLogger(f"{__name__}.paho"))
        client.username_pw_set(self._username, self.pin)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client
        client.connect(self.host, self.port, keepalive=self.KEEPALIVE)
        client.loop_start()

    def _teardown(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            client.loop_stop()
        except Exception:  # noqa: BLE001
            pass

    def _on_connect(self, client, userdata, flags, rc, *args) -> None:
        code = getattr(rc, "value", rc)
        if code != 0:
            # 4/5 (or 134/135 in paho 2) mean wrong username/PIN or not allowed.
            self.auth_failed = code in (4, 5, 134, 135)
            self.last_error = f"controller refused the login (code {code})"
            _LOGGER.warning("Flame Boss %s: %s", self.host, self.last_error)
            self._loop.call_soon_threadsafe(self._disconnected.set)
            self._loop.call_soon_threadsafe(self._first_attempt.set)
            return
        self.auth_failed = False
        self.last_error = None
        _LOGGER.info("Flame Boss %s: connected", self.host)
        topic = (
            f"flameboss/{self.state.device_id}/send/#"
            if self.state.device_id is not None
            else "flameboss/+/send/#"
        )
        # QoS 1 matters: the controller publishes at QoS 1 and hangs up after
        # ~10 s if it doesn't get a PUBACK (paho sends those for us). On each
        # new subscription it sends a full dump of settings and readings.
        client.subscribe(topic, qos=1)
        self._loop.call_soon_threadsafe(self._set_connected, True)

    def _on_disconnect(self, client, userdata, *args) -> None:
        rc = args[1] if len(args) >= 2 else (args[0] if args else None)
        _LOGGER.info("Flame Boss %s: disconnected (%s)", self.host, rc)
        self._loop.call_soon_threadsafe(self._disconnected.set)

    def _on_message(self, client, userdata, message) -> None:
        data = decode_payload(message.payload)
        if data is None:
            _LOGGER.debug("Flame Boss %s: undecodable message on %s", self.host, message.topic)
            return
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Flame Boss %s <- %s %s", self.host, message.topic, _redact(data))
        parts = message.topic.split("/")
        topic_id = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
        self._loop.call_soon_threadsafe(self._handle, data, topic_id)

    # ---- event loop side -------------------------------------------------

    def _handle(self, data: dict[str, Any], topic_id: int | None) -> None:
        if self.state.device_id is None and topic_id is not None:
            self.state.device_id = topic_id
        try:
            event = self.state.apply(data)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Flame Boss: could not handle message %s", _redact(data))
            return
        if event and self._on_event:
            self._on_event(event, data)
        self._notify()

    @property
    def available(self) -> bool:
        """Connected now, or within the last 90 s (rides out brief reconnects)."""
        if self.state.connected:
            return True
        return self._last_connected is not None and time.time() - self._last_connected < 90

    def _set_connected(self, value: bool) -> None:
        if value:
            self._connected_once.set()
            self._first_attempt.set()
        if self.state.connected and not value:
            self._last_connected = time.time()
        if self.state.connected != value:
            self.state.connected = value
            self._notify()

    def _notify(self) -> None:
        if self._on_update:
            self._on_update(self.state)

    # ---- commands --------------------------------------------------------

    async def async_send(self, data: dict[str, Any]) -> None:
        """Send one downlink to the controller."""
        client = self._client
        if client is None or not self.state.connected:
            raise ConnectionError("Not connected to the Flame Boss controller")
        if self.state.device_id is None:
            raise ConnectionError("Controller has not reported its device ID yet")
        topic = f"flameboss/{self.state.device_id}/recv"
        info = await self._loop.run_in_executor(
            None, client.publish, topic, encode_command(data), 1
        )
        _LOGGER.debug("Flame Boss %s -> %s %s (rc %s)", self.host, topic, _redact(data), info.rc)
        if info.rc != 0:
            raise ConnectionError(f"Send failed (code {info.rc})")

    async def async_set_temp(self, celsius: float) -> None:
        """Change the pit setpoint."""
        await self.async_send({"name": "set_temp", "value": encode_temp(celsius)})

    async def async_ack_alarm(self) -> None:
        """Silence and reset any active alert."""
        await self.async_send({"name": "alarm_ack"})
