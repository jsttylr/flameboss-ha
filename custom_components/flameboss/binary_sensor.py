"""Connection and alarm status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FlameBossConfigEntry
from .entity import FlameBossEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: FlameBossConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([FlameBossConnected(entry), FlameBossAlarm(entry)])


class FlameBossConnected(FlameBossEntity, BinarySensorEntity):
    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry) -> None:
        super().__init__(entry, "connected")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._client.state.connected


class FlameBossAlarm(FlameBossEntity, BinarySensorEntity):
    """On while the controller is sounding an alert (pit out of range, meat done, timer)."""

    _attr_translation_key = "alarm"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry) -> None:
        super().__init__(entry, "alarm")

    @property
    def is_on(self) -> bool:
        return self._client.state.alarm_active

    @property
    def extra_state_attributes(self) -> dict:
        s = self._client.state
        return {"pit_alarm": s.pit_alarm.get("status"), "last_alert": s.last_event}
