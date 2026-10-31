"""End-to-end tests against a local mosquitto (127.0.0.1:18830, user fb / PIN 1234) with a fake controller."""
import asyncio
import json

import paho.mqtt.client as mqtt
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util.unit_system import METRIC_SYSTEM

DEV = 424242
PORT = 18830
PIN = "1234"
SEND = f"flameboss/{DEV}/send/data"


DUMP = [
    {"name": "id", "hw_id": 10, "device_id": DEV, "uid": "6Gjn6CUdAAAAAAAAAAAAAA==", "pin": 1234, "sn": 82922, "disabled": False},
    {"name": "cook", "id": 0, "private": False, "next_sec": 1793488624},
    {"name": "cal_user", "t": [0, 0, 0, 0]},
    {"name": "set_temp_limits", "min": 378, "max": 2322},
    {"name": "set_temp", "value": 1767},
    {"name": "wifi", "index": 0, "ssid": "home", "key": "secret"},
    {"name": "wifi_cx", "connected": True, "rssi": -54},
    {"name": "mqtt", "host": "myflameboss.com", "ip": "1.2.3.4", "port": 1883, "tls": False, "username": "D-1", "local_en": True, "keepalive": 15},
    {"name": "meat_alarm", "sensor": 1, "action": "off", "done_temp": 906, "warm_temp": 822},
    {"name": "pit_alarm", "enabled": True, "range": 250},
    {"name": "state", "value": "run"},
    {"name": "labels", "values": ["Pit", "Brisket", "", ""]},
    {"name": "device_temp", "value": -32767},
    {"name": "dc_input", "value": 123},
    {"name": "local_access", "value": "authenticated"},
    {"name": "versions", "hw_id": 10, "app": "4.27.28", "pos": 0, "next_addr": 528384, "revert_avail": None},
    {"name": "temps", "cook_id": 0, "sec": 1793488624, "temps": [1072, 655, -32767, 900], "set_temp": 1767, "blower": 2550},
    {"name": "synced"},
]


class FakeController:
    """Answers {"name":"sync"} with a burst of uplinks, like the real thing."""

    def __init__(self):
        self.received = []
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-controller")
        self.c.username_pw_set("fb", PIN)
        self.c.on_message = self._on_message
        self.c.connect("127.0.0.1", PORT)
        self.c.loop_start()
        self.c.subscribe(f"flameboss/{DEV}/recv")

    def pub(self, msg, sub="data"):
        self.c.publish(f"flameboss/{DEV}/send/{sub}", json.dumps(msg), qos=1)

    def dump(self):
        """What the real controller sends to every new QoS 1 subscriber (captured 2026-10-31)."""
        for up in DUMP:
            self.pub(up, "open" if up["name"] == "temps" else "fw" if up["name"] == "versions" else "data")

    def _on_message(self, c, u, m):
        msg = json.loads(m.payload)
        self.received.append(msg)

    def close(self):
        self.c.loop_stop()
        self.c.disconnect()


async def _wait(hass, pred, secs=10):
    for _ in range(secs * 10):
        await asyncio.sleep(0.1)
        await hass.async_block_till_done()
        if pred():
            return True
    return False


async def test_wrong_pin(hass, socket_enabled):
    result = await hass.config_entries.flow.async_init("flameboss", context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: PORT, "pin": "9999"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_flow_and_entities(hass, socket_enabled):
    hass.config.units = METRIC_SYSTEM
    dev = FakeController()
    # The controller sends a "cook" message on connect; that's how we learn its ID.
    stop = asyncio.Event()

    async def chatter():
        while not stop.is_set():
            dev.dump()
            await asyncio.sleep(0.5)

    task = asyncio.create_task(chatter())
    events = []
    hass.bus.async_listen("flameboss_alert", lambda e: events.append(e.data))
    try:
        result = await hass.config_entries.flow.async_init("flameboss", context={"source": config_entries.SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: PORT, "pin": PIN})
        assert result["type"] is FlowResultType.CREATE_ENTRY, result
        assert result["title"] == f"Flame Boss {DEV}"
        assert result["result"].unique_id == str(DEV)

        p = "sensor.flame_boss_424242_"
        assert await _wait(hass, lambda: (s := hass.states.get(p + "pit_temperature")) and s.state == "107.2")
        assert await _wait(hass, lambda: hass.states.get(p + "status").state == "run")
        st = lambda e: hass.states.get(e).state
        assert st(p + "meat_probe_1") == "65.5"
        assert hass.states.get(p + "meat_probe_1").attributes["label"] == "Brisket"
        assert hass.states.get(p + "meat_probe_1").attributes["done_temp"] == 90.6  # metric test
        assert st(p + "meat_probe_2") == "unknown"
        assert st(p + "meat_probe_3") == "90.0"
        assert st(p + "blower") == "25.5"
        assert st(p + "status") == "run"
        assert st("binary_sensor.flame_boss_424242_connected") == "on"
        assert st("binary_sensor.flame_boss_424242_alarm") == "off"
        n = "number.flame_boss_424242_target_pit_temperature"
        assert st(n) == "176.7"
        assert hass.states.get(n).attributes["max"] == 232.2
        # the dump also re-sends set_temp, so stop chatter before checking commands
        stop.set()
        await task

        await hass.services.async_call("number", "set_value", {"entity_id": n, "value": 120}, blocking=True)
        assert await _wait(hass, lambda: {"name": "set_temp", "value": 1200} in dev.received)

        await hass.services.async_call("button", "press", {"entity_id": "button.flame_boss_424242_silence_alarm"}, blocking=True)
        assert await _wait(hass, lambda: {"name": "alarm_ack"} in dev.received)

        dev.pub({"name": "sound", "config": "alarms", "status": "alarm"})
        dev.pub({"name": "meat_alarm_triggered", "sensor": 1})
        assert await _wait(hass, lambda: st("binary_sensor.flame_boss_424242_alarm") == "on")
        assert await _wait(hass, lambda: events)
        assert events[0]["type"] == "meat_alarm_triggered" and events[0]["sensor"] == 1

        entry = result["result"]
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    finally:
        stop.set()
        if not task.done():
            await task
        dev.close()
