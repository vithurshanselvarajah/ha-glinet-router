from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import FEATURE_MCU_BATTERY, FEATURE_PARENTAL_CONTROL, FEATURE_REPEATER
from ..hub import GLinetHub
from ..models import ParentalGroup

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    _: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: GLinetHub = entry.runtime_data
    entities: list[BinarySensorEntity] = [FanRunningBinarySensor(hub)]
    if hub.feature_enabled(FEATURE_REPEATER):
        entities.extend(
            [
                RepeaterConnectedBinarySensor(hub),
                RepeaterBareModeBinarySensor(hub),
            ]
        )
    if hub.feature_enabled(FEATURE_PARENTAL_CONTROL):
        entities.extend(
            GLinetParentalControlGroupOverrideBinarySensor(hub, group)
            for group in hub.parental_groups.values()
        )
    if hub.feature_enabled(FEATURE_MCU_BATTERY):
        entities.append(GLinetBatteryAbnormalBinarySensor(hub))
    async_add_entities(entities, True)


class RepeaterConnectedBinarySensor(CoordinatorEntity[GLinetHub], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Repeater connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:wifi-sync"

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_binary_sensor/{self._hub.device_mac}/repeater_connected"

    @property
    def is_on(self) -> bool | None:
        return self._hub.repeater_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        status = self._hub.repeater_status
        if status is None:
            return None
        attrs: dict[str, Any] = {}
        if status.ssid:
            attrs["ssid"] = status.ssid
        if status.bssid:
            attrs["bssid"] = status.bssid
        if status.signal is not None:
            attrs["signal"] = status.signal
        if status.wifi_generation:
            attrs["wifi_generation"] = status.wifi_generation
        if status.eap is not None:
            attrs["eap"] = status.eap
        if status.bare_mode is not None:
            attrs["bare_mode"] = status.bare_mode
        return attrs if attrs else None


class RepeaterBareModeBinarySensor(CoordinatorEntity[GLinetHub], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "repeater_bare_mode"
    _attr_icon = "mdi:wifi-off"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_binary_sensor/{self._hub.device_mac}/repeater_bare_mode"

    @property
    def is_on(self) -> bool | None:
        return self._hub.repeater_bare_mode


class FanRunningBinarySensor(CoordinatorEntity[GLinetHub], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Fan status"
    _attr_translation_key = "fan_status"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:fan"

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_binary_sensor/{self._hub.device_mac}/fan_running"

    @property
    def is_on(self) -> bool | None:
        return self._hub.fan_running

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs: dict[str, Any] = {}
        if self._hub.fan_speed is not None:
            attrs["speed"] = self._hub.fan_speed
        if self._hub.fan_temperature_threshold is not None:
            attrs["temperature_threshold"] = self._hub.fan_temperature_threshold
        return attrs if attrs else None


class GLinetBatteryAbnormalBinarySensor(CoordinatorEntity[GLinetHub], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Battery abnormal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-alert"

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_binary_sensor/{self._hub.device_mac}/battery_abnormal"

    @property
    def is_on(self) -> bool | None:
        status = self._hub.router_status
        if status is None or "abnormal" not in status.mcu:
            return None
        return bool(status.mcu.get("abnormal"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        status = self._hub.router_status
        if status is None:
            return None
        attrs: dict[str, Any] = {}
        if "abnormal_type" in status.mcu:
            attrs["abnormal_type"] = status.mcu.get("abnormal_type")
        return attrs or None


class GLinetParentalControlGroupOverrideBinarySensor(
    CoordinatorEntity[GLinetHub],
    BinarySensorEntity,
):
    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: GLinetHub, group: ParentalGroup) -> None:
        super().__init__(hub)
        self._hub = hub
        self._group = group
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return (
            f"glinet_binary_sensor/{self._hub.device_mac}/"
            f"parental_control_group_{self._group.id}_override"
        )

    @property
    def name(self) -> str:
        return f"Parental control {self._group.name} override"

    @property
    def is_on(self) -> bool | None:
        self._group = self._hub.parental_groups.get(self._group.id, self._group)
        return self._group.brief

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs: dict[str, Any] = {}
        if self._group.rule:
            attrs["rule"] = self._group.rule
        if self._group.active_rule_id:
            attrs["active_rule_id"] = self._group.active_rule_id
        if self._group.active_schedule_ids:
            attrs["active_schedule_ids"] = self._group.active_schedule_ids
        return attrs or None
