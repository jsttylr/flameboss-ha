"""Flame Boss / EGG Genius local integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from datetime import timedelta

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .client import FlameBossClient, FlameBossState
from .const import CONF_DEVICE_ID, CONF_PIN, DEFAULT_PORT, DOMAIN, EVENT_ALERT, SIGNAL_UPDATE

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SENSOR]

type FlameBossConfigEntry = ConfigEntry[FlameBossClient]


async def async_setup_entry(hass: HomeAssistant, entry: FlameBossConfigEntry) -> bool:
    """Connect to the controller and set up entities."""
    signal = SIGNAL_UPDATE.format(entry.entry_id)

    fw_seen: list[str] = []

    @callback
    def _updated(state: FlameBossState) -> None:
        async_dispatcher_send(hass, signal)
        # Show the controller's firmware version on the device page.
        app = state.versions.get("app")
        if app and str(app) not in fw_seen:
            fw_seen.append(str(app))
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_device(
                identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
            )
            if device:
                dev_reg.async_update_device(device.id, sw_version=str(app))
        # Remember the device ID once the controller tells us, so commands work
        # right away after a restart.
        if state.device_id is not None and entry.data.get(CONF_DEVICE_ID) != state.device_id:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_DEVICE_ID: state.device_id}
            )

    @callback
    def _event(kind: str, data: dict) -> None:
        # One-off alerts (meat done, pit out of range, ...) become HA events
        # that automations can listen for.
        hass.bus.async_fire(
            EVENT_ALERT,
            {"type": kind, "entry_id": entry.entry_id, "device_id": client.state.device_id,
             **{k: v for k, v in data.items() if k != "name"}},
        )

    client = FlameBossClient(
        hass.loop,
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        pin=entry.data.get(CONF_PIN),
        device_id=entry.data.get(CONF_DEVICE_ID),
        on_update=_updated,
        on_event=_event,
    )
    entry.runtime_data = client
    client.start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    # Re-check availability now and then, so entities go unavailable if the
    # controller disappears (no messages arrive to trigger an update).
    @callback
    def _tick(_now) -> None:
        async_dispatcher_send(hass, signal)

    entry.async_on_unload(async_track_time_interval(hass, _tick, timedelta(seconds=30)))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: FlameBossConfigEntry) -> None:
    """Reload only when the user changed connection settings (not device ID learning)."""
    client = entry.runtime_data
    if (
        entry.data[CONF_HOST] != client.host
        or entry.data.get(CONF_PORT, DEFAULT_PORT) != client.port
        or entry.data.get(CONF_PIN) != client.pin
    ):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FlameBossConfigEntry) -> bool:
    """Disconnect from the controller."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded
