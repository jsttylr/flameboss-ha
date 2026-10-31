"""Pit setpoint control."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FlameBossConfigEntry
from .entity import FlameBossEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: FlameBossConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([FlameBossTargetTemp(entry)])


class FlameBossTargetTemp(FlameBossEntity, NumberEntity):
    _attr_translation_key = "target_temp"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.5

    def __init__(self, entry) -> None:
        super().__init__(entry, "target_temp")

    @property
    def native_value(self) -> float | None:
        return self._client.state.set_temp

    @property
    def native_min_value(self) -> float:
        return self._client.state.min_temp

    @property
    def native_max_value(self) -> float:
        return self._client.state.max_temp

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._client.async_set_temp(value)
        except ConnectionError as err:
            raise HomeAssistantError(str(err)) from err
