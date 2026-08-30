from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.util.dt import utcnow

from ..api.models import RouterStatus
from ..const import (
    FEATURE_CELLULAR,
    FEATURE_FIREWALL,
    FEATURE_MCU_BATTERY,
    FEATURE_OVPN_SERVER,
    FEATURE_REPEATER,
    FEATURE_SMS,
    FEATURE_WG_SERVER,
    WAN_INTERFACE_NAMES,
)
from ..hub import GLinetHub
from ..models import ClientDeviceInfo, RepeaterState
from ..utils import get_first_int, get_first_value

if TYPE_CHECKING:
    from collections.abc import Callable


def _get_cellular_ip(hub: GLinetHub, version: str) -> str | None:
    status = hub.cellular_status
    if not isinstance(status, dict):
        return None
    modems = status.get("modems")
    if not isinstance(modems, list):
        return None
    for modem in modems:
        if not isinstance(modem, dict):
            continue
        network = modem.get("network")
        network_ip = network.get(version) if isinstance(network, dict) else None
        for ip_info in (network_ip, modem.get(version)):
            if not isinstance(ip_info, dict):
                continue
            ip = ip_info.get("ip")
            if ip not in (None, ""):
                return str(ip)
    return None


def _get_traffic_sim(hub: GLinetHub, slot: int) -> dict[str, Any] | None:
    sim_data = getattr(hub, "traffic_sim_data", None)
    if not isinstance(sim_data, dict):
        return None
    record = sim_data.get(slot)
    return record if isinstance(record, dict) else None


def _traffic_sim_present(hub: GLinetHub, slot: int) -> bool:
    record = _get_traffic_sim(hub, slot)
    if record is None:
        return False
    if "present" in record:
        return bool(record.get("present"))
    return int(record.get("traffic_total") or 0) > 0


def _traffic_sim_limit_enabled(hub: GLinetHub, slot: int) -> bool:
    record = _get_traffic_sim(hub, slot)
    if record is None:
        return False
    return bool(record.get("limit_enabled"))


def _traffic_sim_label(slot: int) -> str:
    return f"SIM {slot}"


CELLULAR_TRAFFIC_SIM_PREFIX = "cellular_traffic_sim"


@dataclass(frozen=True, kw_only=True)
class CellularTrafficSensorDescription(SensorEntityDescription):
    slot: int = 1
    sim_type: int = 0
    value_fn: Callable[[GLinetHub, int, int], int | float | None] = lambda hub, slot, sim_type: None
    extra_attributes_fn: Callable[[GLinetHub, int, int], dict[str, Any] | None] | None = None
    requires_limit: bool = False


def _build_cellular_traffic_descriptions(
    slot: int, sim_type: int
) -> tuple[CellularTrafficSensorDescription, ...]:
    return (
        CellularTrafficSensorDescription(
            key="traffic_total",
            name="Traffic total",
            has_entity_name=True,
            icon="mdi:counter",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.DATA_SIZE,
            native_unit_of_measurement="B",
            state_class=SensorStateClass.TOTAL_INCREASING,
            slot=slot,
            sim_type=sim_type,
            value_fn=lambda hub, current_slot, current_sim_type: (
                int(_get_traffic_sim(hub, current_slot).get("traffic_total") or 0)
                if _traffic_sim_present(hub, current_slot)
                else None
            ),
        ),
        CellularTrafficSensorDescription(
            key="days_until_reset",
            name="Days until reset",
            has_entity_name=True,
            icon="mdi:calendar-clock",
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="d",
            slot=slot,
            sim_type=sim_type,
            requires_limit=True,
            value_fn=lambda hub, current_slot, current_sim_type: (
                _get_traffic_sim(hub, current_slot).get("days_until_reset")
                if _traffic_sim_limit_enabled(hub, current_slot)
                else None
            ),
        ),
        CellularTrafficSensorDescription(
            key="data_limit",
            name="Data limit",
            has_entity_name=True,
            icon="mdi:database-cog",
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.DATA_SIZE,
            native_unit_of_measurement="B",
            state_class=SensorStateClass.MEASUREMENT,
            slot=slot,
            sim_type=sim_type,
            requires_limit=True,
            value_fn=lambda hub, current_slot, current_sim_type: (
                _get_traffic_sim(hub, current_slot).get("threshold")
                if _traffic_sim_limit_enabled(hub, current_slot)
                else None
            ),
            extra_attributes_fn=lambda hub, current_slot, current_sim_type: (
                _cellular_traffic_attributes(hub, current_slot)
                if _traffic_sim_limit_enabled(hub, current_slot)
                else None
            ),
        ),
    )


def _cellular_traffic_attributes(hub: GLinetHub, slot: int) -> dict[str, Any] | None:
    record = _get_traffic_sim(hub, slot)
    if record is None:
        return None
    attrs: dict[str, Any] = {
        "slot": slot,
        "sim_type": record.get("sim_type"),
        "limit_enabled": bool(record.get("limit_enabled")),
        "unit": record.get("unit"),
        "reset_period": record.get("reset_period"),
        "day": record.get("day"),
        "hour": record.get("hour"),
        "month": record.get("month"),
        "save_to_flash": bool(record.get("save_to_flash")),
    }
    cleaned = {key: value for key, value in attrs.items() if value is not None}
    return cleaned or None


@dataclass(frozen=True, kw_only=True)
class SystemStatusEntityDescription(SensorEntityDescription):
    value_fn: Callable[[RouterStatus | None], int | float | None]
    extra_attributes_fn: Callable[[RouterStatus | None], dict[str, Any]] | None = None


SYSTEM_SENSORS: tuple[SystemStatusEntityDescription, ...] = (
    SystemStatusEntityDescription(
        key="cpu_temp",
        name="CPU temperature",
        has_entity_name=True,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda s: s.temperature if s else None,
    ),
    SystemStatusEntityDescription(
        key="load_avg1",
        name="Load avg (1m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: (s.load_average or [None])[0] if s else None,
    ),
    SystemStatusEntityDescription(
        key="load_avg5",
        name="Load avg (5m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: (s.load_average or [None, None])[1] if s else None,
    ),
    SystemStatusEntityDescription(
        key="load_avg15",
        name="Load avg (15m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: (s.load_average or [None, None, None])[2] if s else None,
    ),
    SystemStatusEntityDescription(
        key="memory_use",
        name="Memory usage",
        has_entity_name=True,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: _calc_usage_percent(s.memory_total, s.memory_free) if s else None,
        extra_attributes_fn=lambda s: {
            "memory_total": s.memory_total if s else None,
            "memory_free": s.memory_free if s else None,
        },
    ),
    SystemStatusEntityDescription(
        key="flash_use",
        name="Flash usage",
        has_entity_name=True,
        icon="mdi:harddisk",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: _calc_usage_percent(s.flash_total, s.flash_free) if s else None,
        extra_attributes_fn=lambda s: {
            "flash_total": s.flash_total if s else None,
            "flash_free": s.flash_free if s else None,
        },
    ),
)


@dataclass(frozen=True, kw_only=True)
class HubSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[GLinetHub], int | float | str | None]
    extra_attributes_fn: Callable[[GLinetHub], dict[str, Any] | None] | None = None


HUB_SENSORS: tuple[HubSensorEntityDescription, ...] = (
    HubSensorEntityDescription(
        key="connected_clients",
        name="Connected clients",
        has_entity_name=True,
        icon="mdi:devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: hub.online_client_count,
    ),
    HubSensorEntityDescription(
        key="wan_download_rate",
        name="WAN download rate",
        has_entity_name=True,
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement="B/s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: hub.current_traffic_download,
    ),
    HubSensorEntityDescription(
        key="wan_upload_rate",
        name="WAN upload rate",
        has_entity_name=True,
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement="B/s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: hub.current_traffic_upload,
    ),
    HubSensorEntityDescription(
        key="wan_download_total",
        name="WAN total download",
        has_entity_name=True,
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement="B",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda hub: hub.total_traffic_download,
    ),
    HubSensorEntityDescription(
        key="wan_upload_total",
        name="WAN total upload",
        has_entity_name=True,
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement="B",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda hub: hub.total_traffic_upload,
    ),
    HubSensorEntityDescription(
        key="cellular_ipv4",
        name="Cellular WAN IPv4",
        has_entity_name=True,
        icon="mdi:ip-network",
        value_fn=lambda hub: _get_cellular_ip(hub, "ipv4"),
    ),
    HubSensorEntityDescription(
        key="cellular_ipv6",
        name="Cellular WAN IPv6",
        has_entity_name=True,
        icon="mdi:ip-network",
        value_fn=lambda hub: _get_cellular_ip(hub, "ipv6"),
    ),
    HubSensorEntityDescription(
        key="firewall_rules",
        name="Firewall rules",
        has_entity_name=True,
        icon="mdi:security",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: len(hub._firewall_rules),
    ),
    HubSensorEntityDescription(
        key="port_forwards",
        name="Port forwards",
        has_entity_name=True,
        icon="mdi:router-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: len(hub._port_forwards),
    ),
    HubSensorEntityDescription(
        key="battery_temperature",
        name="Battery temperature",
        has_entity_name=True,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda hub: _mcu_value(hub, "temperature"),
    ),
    HubSensorEntityDescription(
        key="battery_charge",
        name="Battery charge",
        has_entity_name=True,
        icon="mdi:battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda hub: _mcu_value(hub, "charge_percent"),
        extra_attributes_fn=lambda hub: {
            "charge_count": _mcu_value(hub, "charge_cnt"),
            "fast_charge": _mcu_value(hub, "fastcharge"),
            "abnormal_type": _mcu_value(hub, "abnormal_type"),
        },
    ),
    HubSensorEntityDescription(
        key="battery_charging_status",
        name="Battery charging status",
        has_entity_name=True,
        icon="mdi:battery-charging",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["not_charging", "charging"],
        value_fn=lambda hub: _battery_charging_status(hub),
    ),
    HubSensorEntityDescription(
        key="cellular_apn",
        name="Cellular APN",
        has_entity_name=True,
        icon="mdi:access-point-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda hub: get_first_value(
            hub.cellular_status,
            ("apn",),
            nested=("modem", "cellular", "sim", "simcard"),
        ),
    ),
    HubSensorEntityDescription(
        key="cellular_rsrp",
        name="Cellular RSRP",
        has_entity_name=True,
        icon="mdi:signal-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: get_first_int(
            hub.cellular_status,
            ("rsrp",),
            nested=("modem", "cellular", "sim", "signal"),
        ),
    ),
    HubSensorEntityDescription(
        key="cellular_rsrq",
        name="Cellular RSRQ",
        has_entity_name=True,
        icon="mdi:signal-distance-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: get_first_int(
            hub.cellular_status,
            ("rsrq",),
            nested=("modem", "cellular", "sim", "signal"),
        ),
    ),
    HubSensorEntityDescription(
        key="cellular_sinr",
        name="Cellular SINR",
        has_entity_name=True,
        icon="mdi:signal-3g",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: get_first_int(
            hub.cellular_status,
            ("sinr",),
            nested=("modem", "cellular", "sim", "signal"),
        ),
    ),
    HubSensorEntityDescription(
        key="cellular_band",
        name="Cellular band",
        has_entity_name=True,
        icon="mdi:cellphone-wireless",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda hub: get_first_value(
            hub.cellular_status,
            ("band", "network_type", "service_type"),
            nested=("modem", "cellular", "sim"),
        ),
    ),
    HubSensorEntityDescription(
        key="sms_messages",
        name="Unread messages",
        has_entity_name=True,
        icon="mdi:email-alert",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: sum(1 for m in hub.sms_messages.values() if m.status == 0),
        extra_attributes_fn=lambda hub: {
            "unread_count": sum(1 for m in hub.sms_messages.values() if m.status == 0),
            "message_count": len(hub.sms_messages),
            "incoming_count": sum(
                1 for m in hub.sms_messages.values() if m.direction == "incoming"
            ),
            "outgoing_count": sum(
                1 for m in hub.sms_messages.values() if m.direction == "outgoing"
            ),
            "messages": [
                {
                    "id": message_id,
                    "phone_number": message.phone_number,
                    "direction": message.direction,
                    "status": message.status_label,
                    "timestamp": message.timestamp,
                    "text": message.text,
                }
                for message_id, message in hub.sms_messages.items()
            ],
        },
    ),
    HubSensorEntityDescription(
        key="repeater_state",
        name="Repeater state",
        has_entity_name=True,
        icon="mdi:wifi-sync",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "initializing",
            "not_used",
            "connecting",
            "connected",
            "failed",
            "wan_available",
        ],
        value_fn=lambda hub: _repeater_state_value(hub),
        extra_attributes_fn=lambda hub: _repeater_state_attributes(hub),
    ),
    HubSensorEntityDescription(
        key="repeater_ssid",
        name="Repeater SSID",
        has_entity_name=True,
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda hub: hub.repeater_status.ssid if hub.repeater_status else None,
    ),
    HubSensorEntityDescription(
        key="repeater_signal",
        name="Repeater signal",
        has_entity_name=True,
        icon="mdi:wifi-strength-2",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: hub.repeater_status.signal if hub.repeater_status else None,
    ),
    HubSensorEntityDescription(
        key="repeater_ip",
        name="Repeater IP address",
        has_entity_name=True,
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda hub: hub.repeater_status.ipv4_address if hub.repeater_status else None,
    ),
    HubSensorEntityDescription(
        key="repeater_gateway",
        name="Repeater gateway",
        has_entity_name=True,
        icon="mdi:router-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda hub: hub.repeater_status.ipv4_gateway if hub.repeater_status else None,
    ),
    HubSensorEntityDescription(
        key="repeater_dns",
        name="Repeater DNS",
        has_entity_name=True,
        icon="mdi:dns",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda hub: (
            hub.repeater_status.ipv4_dns[0]
            if hub.repeater_status and hub.repeater_status.ipv4_dns
            else None
        ),
        extra_attributes_fn=lambda hub: (
            {"dns_servers": hub.repeater_status.ipv4_dns}
            if hub.repeater_status and hub.repeater_status.ipv4_dns
            else None
        ),
    ),
    HubSensorEntityDescription(
        key="repeater_bssid",
        name="Repeater BSSID",
        has_entity_name=True,
        icon="mdi:access-point-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda hub: hub.repeater_status.bssid if hub.repeater_status else None,
    ),
    HubSensorEntityDescription(
        key="fan_speed",
        name="Fan speed",
        translation_key="fan_speed",
        has_entity_name=True,
        icon="mdi:fan",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="RPM",
        value_fn=lambda hub: hub.fan_speed,
        extra_attributes_fn=lambda hub: {
            "running": hub.fan_running,
            "temperature_threshold": hub.fan_temperature_threshold,
        },
    ),
    HubSensorEntityDescription(
        key="fan_temperature",
        name="Fan threshold temperature",
        translation_key="fan_temperature",
        has_entity_name=True,
        icon="mdi:thermometer-auto",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: hub.fan_temperature_threshold,
    ),
    HubSensorEntityDescription(
        key="wg_server_users",
        name="WireGuard server users",
        has_entity_name=True,
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: hub.wg_server_connected_users,
    ),
    HubSensorEntityDescription(
        key="ovpn_server_users",
        name="OpenVPN server users",
        has_entity_name=True,
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda hub: hub.ovpn_server_connected_users,
    ),
)


FEATURE_SENSOR_MAP: dict[str, str] = {
    "cellular_rsrp": FEATURE_CELLULAR,
    "cellular_rsrq": FEATURE_CELLULAR,
    "cellular_sinr": FEATURE_CELLULAR,
    "cellular_band": FEATURE_CELLULAR,
    "cellular_apn": FEATURE_CELLULAR,
    "sms_messages": FEATURE_SMS,
    "repeater_state": FEATURE_REPEATER,
    "repeater_ssid": FEATURE_REPEATER,
    "repeater_signal": FEATURE_REPEATER,
    "repeater_ip": FEATURE_REPEATER,
    "repeater_gateway": FEATURE_REPEATER,
    "repeater_dns": FEATURE_REPEATER,
    "repeater_bssid": FEATURE_REPEATER,
    "wg_server_users": FEATURE_WG_SERVER,
    "ovpn_server_users": FEATURE_OVPN_SERVER,
    "firewall_rules": FEATURE_FIREWALL,
    "port_forwards": FEATURE_FIREWALL,
    "battery_temperature": FEATURE_MCU_BATTERY,
    "battery_charge": FEATURE_MCU_BATTERY,
    "battery_charging_status": FEATURE_MCU_BATTERY,
}


@dataclass(frozen=True, kw_only=True)
class ClientSensorEntityDescription(SensorEntityDescription):
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    value_fn: Callable[[ClientDeviceInfo], int | str | None]


CLIENT_BANDWIDTH_SENSORS: tuple[ClientSensorEntityDescription, ...] = (
    ClientSensorEntityDescription(
        key="rx_rate",
        name="Download rate",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement="B/s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.rx_rate,
    ),
    ClientSensorEntityDescription(
        key="tx_rate",
        name="Upload rate",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement="B/s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.tx_rate,
    ),
    ClientSensorEntityDescription(
        key="total_rx",
        name="Total download",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement="B",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda device: device.total_rx,
    ),
    ClientSensorEntityDescription(
        key="total_tx",
        name="Total upload",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement="B",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda device: device.total_tx,
    ),
)


CLIENT_DIAGNOSTIC_SENSORS: tuple[ClientSensorEntityDescription, ...] = (
    ClientSensorEntityDescription(
        key="ip_address",
        name="IP address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.ip_address,
    ),
)


def _repeater_state_value(hub: GLinetHub) -> str | None:
    if hub.repeater_status is None:
        return None
    state_map = {
        RepeaterState.INITIALIZING: "initializing",
        RepeaterState.NOT_USED: "not_used",
        RepeaterState.CONNECTING: "connecting",
        RepeaterState.CONNECTED: "connected",
        RepeaterState.FAILED: "failed",
        RepeaterState.WAN_AVAILABLE: "wan_available",
    }
    return state_map.get(hub.repeater_status.state)


def _repeater_state_attributes(hub: GLinetHub) -> dict[str, Any] | None:
    if hub.repeater_status is None:
        return None
    attrs: dict[str, Any] = {}
    if hub.repeater_status.bssid:
        attrs["bssid"] = hub.repeater_status.bssid
    if hub.repeater_status.fail_type:
        attrs["fail_type"] = hub.repeater_status.fail_type
    if hub.repeater_status.device:
        attrs["device"] = hub.repeater_status.device
    if hub.repeater_status.wifi_generation:
        attrs["wifi_generation"] = hub.repeater_status.wifi_generation
    if hub.repeater_status.eap is not None:
        attrs["eap"] = hub.repeater_status.eap
    if hub.repeater_status.bare_mode is not None:
        attrs["bare_mode"] = hub.repeater_status.bare_mode
    return attrs if attrs else None


def _repeater_state_is(hub: GLinetHub, states: set) -> bool:

    status = hub.repeater_status
    return status is not None and status.state in states


def _repeater_link_sensor_available(hub: GLinetHub) -> bool:
    return _repeater_state_is(
        hub,
        {
            RepeaterState.CONNECTING,
            RepeaterState.CONNECTED,
            RepeaterState.WAN_AVAILABLE,
        },
    )


def _repeater_network_sensor_available(hub: GLinetHub) -> bool:
    return _repeater_state_is(
        hub,
        {
            RepeaterState.CONNECTED,
            RepeaterState.WAN_AVAILABLE,
        },
    )


def _wan_interfaces(hub: GLinetHub) -> list[dict[str, Any]]:
    interfaces = hub.kmwan_status.get("interfaces", [])
    if not isinstance(interfaces, list):
        return []
    return [iface for iface in interfaces if isinstance(iface, dict)]


def _wan_interface_label(interface_name: str) -> str:
    return WAN_INTERFACE_NAMES.get(interface_name, interface_name)


def _wan_interface_by_name(hub: GLinetHub, interface_name: str) -> dict[str, Any] | None:
    if interface_name == "modem_0001" and getattr(hub, "is_firmware_4_9_or_above", False):
        for candidate in ("modem_0001_s1", "modem_0001_s2"):
            entry = _wan_lookup_exact(hub, candidate)
            if entry is not None and entry.get("status_v4") == 0:
                return entry
        for candidate in ("modem_0001_s1", "modem_0001_s2"):
            entry = _wan_lookup_exact(hub, candidate)
            if entry is not None:
                return entry
        return None
    return _wan_lookup_exact(hub, interface_name)


def _wan_lookup_exact(hub: GLinetHub, interface_name: str) -> dict[str, Any] | None:
    for interface in _wan_interfaces(hub):
        if interface.get("interface") == interface_name:
            return interface
    return None


def _wan_protocol_field(protocol: str) -> str:
    return "status_v6" if protocol == "ipv6" else "status_v4"


def _wan_protocol_status(interface: dict[str, Any] | None, protocol: str) -> str:
    if interface is None:
        return "Unknown"
    value = interface.get(_wan_protocol_field(protocol))
    if value == 0:
        return "Up"
    if value == 1:
        return "Down"
    return "Unknown"


def _wan_monitor_parts(monitor: str) -> tuple[str, str] | None:
    interface, separator, protocol = monitor.partition(":")
    if not separator or protocol not in {"ipv4", "ipv6"} or not interface:
        return None
    return interface, protocol


def _calc_usage_percent(total: Any, free: Any) -> float | None:
    if not isinstance(total, (int, float)) or total <= 0:
        return None
    if not isinstance(free, (int, float)) or free < 0:
        return None
    value = 100 * (1 - free / total)
    return value if 0 <= value <= 100 else None


def _mcu_value(hub: GLinetHub, key: str) -> Any:
    status = hub.router_status
    if status is None:
        return None
    return status.mcu.get(key)


def _battery_charging_status(hub: GLinetHub) -> str | None:
    value = _mcu_value(hub, "charging_status")
    if value == 1:
        return "charging"
    if value == 0:
        return "not_charging"
    return None


def _sensor_is_enabled(hub: GLinetHub, description: HubSensorEntityDescription) -> bool:
    if description.key in {"cellular_ipv4", "cellular_ipv6"}:
        monitors = hub.wan_status_monitors
        protocol = "ipv4" if description.key == "cellular_ipv4" else "ipv6"
        if monitors is None:
            return any(iface.get("interface") == "modem_0001" for iface in _wan_interfaces(hub))
        return f"modem_0001:{protocol}" in monitors

    feature = FEATURE_SENSOR_MAP.get(description.key)
    return feature is None or hub.feature_enabled(feature)


def _resolve_uptime(seconds_uptime: float, last_value: datetime | None) -> datetime:
    delta_uptime = utcnow() - timedelta(seconds=seconds_uptime)
    if not last_value or abs((delta_uptime - last_value).total_seconds()) > 15:
        return delta_uptime
    return last_value
