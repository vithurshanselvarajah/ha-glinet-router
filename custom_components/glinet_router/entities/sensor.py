from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN, FEATURE_CELLULAR, FEATURE_REPEATER
from ..hub import GLinetHub
from ..models import ClientDeviceInfo
from ..utils import channel_to_band
from .sensor_descriptions import (
    CELLULAR_TRAFFIC_SIM_PREFIX,
    CLIENT_BANDWIDTH_SENSORS,
    CLIENT_DIAGNOSTIC_SENSORS,
    HUB_SENSORS,
    SYSTEM_SENSORS,
    CellularTrafficSensorDescription,
    ClientSensorEntityDescription,
    HubSensorEntityDescription,
    SystemStatusEntityDescription,
    _build_cellular_traffic_descriptions,
    _repeater_link_sensor_available,
    _repeater_network_sensor_available,
    _resolve_uptime,
    _sensor_is_enabled,
    _traffic_sim_label,
    _traffic_sim_present,
    _wan_interface_by_name,
    _wan_interface_label,
    _wan_interfaces,
    _wan_monitor_parts,
    _wan_protocol_status,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: GLinetHub = entry.runtime_data
    tracked: set[str] = set()
    entities: list[SensorEntity] = [
        SystemStatusSensor(hub=hub, entity_description=description)
        for description in SYSTEM_SENSORS
        if description.value_fn(hub.router_status) is not None
    ]
    entities.extend(
        HubStatusSensor(hub=hub, entity_description=description)
        for description in HUB_SENSORS
        if _sensor_is_enabled(hub, description)
    )
    wan_status_monitors = hub.wan_status_monitors
    if wan_status_monitors is None:
        for interface in _wan_interfaces(hub):
            interface_name = interface.get("interface")
            if interface_name:
                entities.append(WanStatusSensor(hub, str(interface_name), {"ipv4", "ipv6"}))
    else:
        monitored_interfaces: dict[str, set[str]] = {}
        for monitor in sorted(wan_status_monitors):
            parts = _wan_monitor_parts(monitor)
            if parts is not None:
                interface, protocol = parts
                monitored_interfaces.setdefault(interface, set()).add(protocol)
        entities.extend(
            WanStatusSensor(hub, interface, protocols)
            for interface, protocols in monitored_interfaces.items()
            if protocols
        )
    entities.append(
        SystemUptimeSensor(
            hub=hub,
            entity_description=SystemStatusEntityDescription(
                key="uptime",
                name="Uptime",
                has_entity_name=True,
                icon="mdi:clock",
                entity_category=EntityCategory.DIAGNOSTIC,
                device_class=SensorDeviceClass.TIMESTAMP,
                value_fn=lambda _: None,
            ),
        )
    )
    if hub.feature_enabled(FEATURE_REPEATER):
        entities.append(RepeaterChannelSensor(hub=hub))

    if hub.feature_enabled(FEATURE_CELLULAR):
        for slot, sim_record in sorted(
            (hub.traffic_sim_data or {}).items(),
            key=lambda item: item[0] if isinstance(item[0], int) else int(item[0]),
        ):
            if not isinstance(sim_record, dict):
                continue
            if not sim_record.get("present"):
                continue
            sim_type = int(sim_record.get("sim_type") or 0)
            limit_enabled = bool(sim_record.get("limit_enabled"))
            for description in _build_cellular_traffic_descriptions(slot, sim_type):
                if description.requires_limit and not limit_enabled:
                    continue
                entities.append(CellularTrafficSensor(hub=hub, entity_description=description))

    async_add_entities(entities, True)

    @callback
    def register_client_sensors() -> None:
        new_entities: list[SensorEntity] = []
        for mac, device in hub.tracked_devices.items():
            for description in CLIENT_BANDWIDTH_SENSORS + CLIENT_DIAGNOSTIC_SENSORS:
                unique_id = f"glinet_client_sensor/{mac}/{description.key}"
                if unique_id in tracked:
                    continue
                tracked.add(unique_id)
                new_entities.append(ClientSensor(hub, device, description))
        if new_entities:
            async_add_entities(new_entities)

    register_cellular_limit_sensors = _make_register_cellular_limit_sensors_callback(
        hub, async_add_entities
    )

    register_client_sensors()
    entry.async_on_unload(
        async_dispatcher_connect(
            hub.hass,
            hub.event_device_added,
            register_client_sensors,
        )
    )
    entry.async_on_unload(
        async_dispatcher_connect(
            hub.hass,
            hub.event_cellular_traffic_config_updated,
            register_cellular_limit_sensors,
        )
    )


def _make_register_cellular_limit_sensors_callback(
    hub: GLinetHub, async_add_entities: AddEntitiesCallback
) -> Any:
    @callback
    def _register() -> None:
        if not hub.feature_enabled(FEATURE_CELLULAR):
            return
        from homeassistant.helpers import entity_registry as er

        entity_registry = er.async_get(hub.hass)
        existing_ids = {
            entry.unique_id
            for entry in er.async_entries_for_config_entry(entity_registry, hub._entry.entry_id)
            if entry.unique_id.startswith(
                f"glinet_sensor/{hub.device_mac}/{CELLULAR_TRAFFIC_SIM_PREFIX}_"
            )
        }
        new_entities: list[SensorEntity] = []
        for slot, sim_record in sorted(
            (hub.traffic_sim_data or {}).items(),
            key=lambda item: item[0] if isinstance(item[0], int) else int(item[0]),
        ):
            if not isinstance(sim_record, dict):
                continue
            if not sim_record.get("present"):
                continue
            if not sim_record.get("limit_enabled"):
                continue
            sim_type = int(sim_record.get("sim_type") or 0)
            for description in _build_cellular_traffic_descriptions(slot, sim_type):
                if not description.requires_limit:
                    continue
                candidate = CellularTrafficSensor(hub=hub, entity_description=description)
                if candidate.unique_id in existing_ids:
                    continue
                new_entities.append(candidate)
        if new_entities:
            async_add_entities(new_entities)

    return _register


class GLinetSensorBase(CoordinatorEntity[GLinetHub], SensorEntity):
    def __init__(self, hub: GLinetHub, entity_description: SystemStatusEntityDescription) -> None:
        super().__init__(hub)
        self.hub = hub
        self.entity_description = entity_description
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_sensor/{self.hub.device_mac}/system_{self.entity_description.key}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_attributes_fn is None:
            return None
        return self.entity_description.extra_attributes_fn(self.hub.router_status)


class SystemStatusSensor(GLinetSensorBase):
    @property
    def native_value(self) -> int | float | None:
        return self.entity_description.value_fn(self.hub.router_status)


class HubStatusSensor(CoordinatorEntity[GLinetHub], SensorEntity):
    def __init__(self, hub: GLinetHub, entity_description: HubSensorEntityDescription) -> None:
        super().__init__(hub)
        self.hub = hub
        self.entity_description = entity_description
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_sensor/{self.hub.device_mac}/{self.entity_description.key}"

    @property
    def native_value(self) -> int | float | str | None:
        return self.entity_description.value_fn(self.hub)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_attributes_fn is None:
            return None
        return self.entity_description.extra_attributes_fn(self.hub)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self.entity_description.key in {"cellular_ipv4", "cellular_ipv6"}:
            return self.native_value is not None
        if self.entity_description.key in {
            "repeater_ssid",
            "repeater_signal",
            "repeater_bssid",
        }:
            return _repeater_link_sensor_available(self.hub)
        if self.entity_description.key in {
            "repeater_ip",
            "repeater_gateway",
            "repeater_dns",
        }:
            return _repeater_network_sensor_available(self.hub)
        return True


class CellularTrafficSensor(CoordinatorEntity[GLinetHub], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        hub: GLinetHub,
        entity_description: CellularTrafficSensorDescription,
    ) -> None:
        super().__init__(hub)
        self.hub = hub
        self.entity_description = entity_description
        self._slot = entity_description.slot
        self._sim_type = entity_description.sim_type
        self._attr_name = f"{_traffic_sim_label(self._slot)} {entity_description.name}".strip()
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return (
            f"glinet_sensor/{self.hub.device_mac}/"
            f"{CELLULAR_TRAFFIC_SIM_PREFIX}_{self._slot}_{self._sim_type}_"
            f"{self.entity_description.key}"
        )

    @property
    def native_value(self) -> int | float | None:
        return self.entity_description.value_fn(self.hub, self._slot, self._sim_type)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_attributes_fn is None:
            return None
        return self.entity_description.extra_attributes_fn(self.hub, self._slot, self._sim_type)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if not _traffic_sim_present(self.hub, self._slot):
            return False
        return self.native_value is not None


class WanStatusSensor(CoordinatorEntity[GLinetHub], SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:web"

    def __init__(self, hub: GLinetHub, interface_name: str, protocols: set[str]) -> None:
        super().__init__(hub)
        self.hub = hub
        self._interface_name = interface_name
        self._interface_label = _wan_interface_label(interface_name)
        self._protocols = protocols
        self._attr_name = f"{self._interface_label} status"
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_sensor/{self.hub.device_mac}/wan_status_{self._interface_name}"

    @property
    def native_value(self) -> str:
        interface = _wan_interface_by_name(self.hub, self._interface_name)
        statuses = [
            _wan_protocol_status(interface, protocol) for protocol in sorted(self._protocols)
        ]
        if not statuses or all(status == "Unknown" for status in statuses):
            return "Unknown"
        if any(status == "Up" for status in statuses):
            return "Up"
        if all(status == "Down" for status in statuses):
            return "Down"
        return "Unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        interface = _wan_interface_by_name(self.hub, self._interface_name) or {}
        resolved_interface_name = str(interface.get("interface") or self._interface_name)
        resolved_label = (
            _wan_interface_label(resolved_interface_name)
            if resolved_interface_name != self._interface_name
            else self._interface_label
        )
        return {
            "interface": resolved_interface_name,
            "interface_name": resolved_label,
            "requested_interface": self._interface_name,
            "monitored_protocols": sorted(self._protocols),
            "ipv4_status": _wan_protocol_status(interface, "ipv4"),
            "ipv6_status": _wan_protocol_status(interface, "ipv6"),
            "status_v4": interface.get("status_v4"),
            "status_v6": interface.get("status_v6"),
        }


class SystemUptimeSensor(GLinetSensorBase):
    _current_value: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        status = self.hub.router_status
        uptime = status.uptime if status else None
        if not isinstance(uptime, (int, float)):
            return None
        self._current_value = _resolve_uptime(float(uptime), self._current_value)
        return self._current_value


class ClientSensor(CoordinatorEntity[GLinetHub], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hub: GLinetHub,
        device: ClientDeviceInfo,
        entity_description: ClientSensorEntityDescription,
    ) -> None:
        super().__init__(hub)
        self._hub = hub
        self._device = device
        self.entity_description = entity_description
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, format_mac(device.mac))},
            name=device.name or device.mac,
            via_device=(DOMAIN, self._hub.router_id),
        )

    @property
    def unique_id(self) -> str:
        return f"glinet_client_sensor/{self._device.mac}/{self.entity_description.key}"

    @property
    def native_value(self) -> int | str | None:
        self._device = self._hub.tracked_devices.get(self._device.mac, self._device)
        return self.entity_description.value_fn(self._device)


class RepeaterChannelSensor(CoordinatorEntity[GLinetHub], SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:radio-tower"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "repeater_channel"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info
        self._attr_options = ["2_4ghz", "5ghz"]

    @property
    def unique_id(self) -> str:
        return f"glinet_sensor/{self._hub.device_mac}/repeater_channel"

    @property
    def native_value(self) -> str | None:
        if not self._hub.repeater_status:
            return None
        channel = self._hub.repeater_status.channel
        if channel is None:
            return None
        return channel_to_band(channel)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self._hub.repeater_status:
            return None
        channel = self._hub.repeater_status.channel
        return {"channel": channel, "band": channel_to_band(channel)}

    @property
    def available(self) -> bool:
        return super().available and _repeater_link_sensor_available(self._hub)


__all__ = [
    "CellularTrafficSensor",
    "CellularTrafficSensorDescription",
    "ClientSensor",
    "ClientSensorEntityDescription",
    "GLinetSensorBase",
    "HubSensorEntityDescription",
    "HubStatusSensor",
    "RepeaterChannelSensor",
    "SystemStatusEntityDescription",
    "SystemStatusSensor",
    "SystemUptimeSensor",
    "WanStatusSensor",
]
