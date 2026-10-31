"""Temperature and blower sensors."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FlameBossConfigEntry
from .client import decode_temp
from .const import PROBE_SLOTS
from .entity import FlameBossEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: FlameBossConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list[SensorEntity] = [FlameBossProbe(entry, i) for i in range(PROBE_SLOTS)]
    entities += [
        FlameBossBlower(entry),
        FlameBossSetpoint(entry),
        FlameBossDeviceId(entry),
        FlameBossRunState(entry),
        FlameBossWifi(entry),
        FlameBossVoltage(entry),
        FlameBossTimerEnd(entry),
    ]
    async_add_entities(entities)


class FlameBossProbe(FlameBossEntity, SensorEntity):
    """Pit (slot 0) or meat probe (slots 1-3). Unknown when unplugged."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 0

    def __init__(self, entry, index: int) -> None:
        super().__init__(entry, "pit_temp" if index == 0 else f"meat_{index}_temp")
        self._index = index
        self._attr_translation_key = "pit_temp" if index == 0 else "meat_temp"
        if index:
            self._attr_translation_placeholders = {"number": str(index)}

    @property
    def native_value(self) -> float | None:
        temps = self._client.state.temps
        return temps[self._index] if self._index < len(temps) else None

    @property
    def extra_state_attributes(self) -> dict | None:
        s = self._client.state
        attrs = {}
        if self._index < len(s.labels) and s.labels[self._index]:
            attrs["label"] = s.labels[self._index]
        alarm = s.meat_alarms.get(self._index)
        if alarm:
            attrs["done_temp"] = decode_temp(alarm.get("done_temp"))
            attrs["alarm_action"] = alarm.get("action")
        return attrs or None


class FlameBossBlower(FlameBossEntity, SensorEntity):
    _attr_translation_key = "blower"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, entry) -> None:
        super().__init__(entry, "blower")

    @property
    def native_value(self) -> float | None:
        return self._client.state.blower


class FlameBossSetpoint(FlameBossEntity, SensorEntity):
    """Read-only copy of the pit setpoint (handy for graphs next to the pit temp)."""

    _attr_translation_key = "set_temp"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 0

    def __init__(self, entry) -> None:
        super().__init__(entry, "set_temp_sensor")

    @property
    def native_value(self) -> float | None:
        return self._client.state.set_temp


class FlameBossDeviceId(FlameBossEntity, SensorEntity):
    """The controller's ID, which it announces itself (no label needed)."""

    _attr_translation_key = "device_id"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry) -> None:
        super().__init__(entry, "device_id")

    @property
    def native_value(self) -> int | None:
        return self._client.state.device_id


class FlameBossRunState(FlameBossEntity, SensorEntity):
    """idle / run / error, as reported by the controller."""

    _attr_translation_key = "run_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "run", "error", "production"]

    def __init__(self, entry) -> None:
        super().__init__(entry, "run_state")

    @property
    def native_value(self) -> str | None:
        v = self._client.state.run_state
        return v if v in self._attr_options else None


class FlameBossWifi(FlameBossEntity, SensorEntity):
    _attr_translation_key = "wifi_rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry) -> None:
        super().__init__(entry, "wifi_rssi")

    @property
    def native_value(self) -> int | None:
        return self._client.state.wifi_rssi


class FlameBossVoltage(FlameBossEntity, SensorEntity):
    _attr_translation_key = "dc_input"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry) -> None:
        super().__init__(entry, "dc_input")

    @property
    def native_value(self) -> float | None:
        return self._client.state.dc_input


class FlameBossTimerEnd(FlameBossEntity, SensorEntity):
    """When the controller's cook timer runs out (blank when no timer is running)."""

    _attr_translation_key = "timer_end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry) -> None:
        super().__init__(entry, "timer_end")

    @property
    def native_value(self):
        from datetime import datetime, timezone

        t = self._client.state.timer
        if t.get("status") == "active" and t.get("ends_at"):
            return datetime.fromtimestamp(int(t["ends_at"]), tz=timezone.utc)
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        t = self._client.state.timer
        if not t:
            return None
        return {"action": t.get("action"), "status": t.get("status"), "hold_temp": decode_temp(t.get("hold"))}
