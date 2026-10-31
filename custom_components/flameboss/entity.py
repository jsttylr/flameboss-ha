"""Base entity for Flame Boss."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .client import FlameBossClient
from .const import DOMAIN, SIGNAL_UPDATE


class FlameBossEntity(Entity):
    """Common bits: device info, push updates, availability."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self._entry = entry
        self._client: FlameBossClient = entry.runtime_data
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        versions = self._client.state.versions
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="Flame Boss",
            model="Flame Boss / EGG Genius",
            sw_version=str(versions["app"]) if versions.get("app") is not None else None,
            configuration_url=f"http://{self._client.host}/",
        )

    @property
    def available(self) -> bool:
        return self._client.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATE.format(self._entry.entry_id), self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
