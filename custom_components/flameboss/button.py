"""Silence-alarm button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FlameBossConfigEntry
from .entity import FlameBossEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: FlameBossConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([FlameBossSilence(entry)])


class FlameBossSilence(FlameBossEntity, ButtonEntity):
    _attr_translation_key = "silence_alarm"

    def __init__(self, entry) -> None:
        super().__init__(entry, "silence_alarm")

    async def async_press(self) -> None:
        try:
            await self._client.async_ack_alarm()
        except ConnectionError as err:
            raise HomeAssistantError(str(err)) from err
