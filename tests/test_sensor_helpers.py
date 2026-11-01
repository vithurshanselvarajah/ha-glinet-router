from __future__ import annotations

import sys
import types
from dataclasses import dataclass

from custom_components.glinet_router.utils import get_first_int, get_first_value


def _install_sensor_dependency_stubs() -> None:
    if _homeassistant_is_importable():
        return

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        name: str | None = None
        has_entity_name: bool | None = None
        icon: str | None = None
        entity_category: str | None = None
        device_class: str | None = None
        native_unit_of_measurement: str | None = None
        state_class: str | None = None
        suggested_display_precision: int | None = None
        options: list[str] | None = None

    sensor = types.ModuleType("homeassistant.components.sensor")
    sensor.SensorDeviceClass = types.SimpleNamespace(
        DATA_RATE="data_rate",
        DATA_SIZE="data_size",
        ENUM="enum",
        TEMPERATURE="temperature",
        TIMESTAMP="timestamp",
    )
    sensor.SensorEntity = object
    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.SensorStateClass = types.SimpleNamespace(
        MEASUREMENT="measurement",
        TOTAL_INCREASING="total_increasing",
        TOTAL="total",
    )
    sys.modules.setdefault("homeassistant.components.sensor", sensor)

    const = sys.modules["homeassistant.const"]
    const.PERCENTAGE = "%"
    const.EntityCategory = types.SimpleNamespace(DIAGNOSTIC="diagnostic", CONFIG="config")
    const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="C")

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda func: func
    sys.modules.setdefault("homeassistant.core", core)

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    sys.modules.setdefault("homeassistant.helpers.entity_platform", entity_platform)


def _homeassistant_is_importable() -> bool:
    import importlib.util

    try:
        spec = importlib.util.find_spec("homeassistant")
    except (ValueError, ImportError):
        return False
    if spec is None:
        return False
    module = sys.modules.get("homeassistant")
    if module is not None and getattr(module, "__spec__", None) is None:
        return False
    return True


_install_sensor_dependency_stubs()


def test_first_int_searches_nested_payloads() -> None:
    payload = {"wan": {"status": {"traffic": {"bytes_rx": 1234}}}}

    assert get_first_int(payload, ("bytes_rx",)) == 1234


def test_first_value_searches_nested_payloads() -> None:
    payload = {"modem": {"details": {"operator_name": "Example Mobile"}}}

    assert get_first_value(payload, ("operator_name",)) == "Example Mobile"


def test_wan_status_helpers_report_interface_protocol_state() -> None:
    from custom_components.glinet_router.entities.sensor import (
        WanStatusSensor,
        _wan_interface_by_name,
        _wan_protocol_status,
    )

    hub = types.SimpleNamespace(
        kmwan_status={
            "interfaces": [
                {"interface": "wan", "status_v4": 0, "status_v6": 1},
                {"interface": "wwan", "status_v4": 1, "status_v6": 0},
            ]
        }
    )

    wan = _wan_interface_by_name(hub, "wan")
    assert _wan_protocol_status(wan, "ipv4") == "Up"
    assert _wan_protocol_status(wan, "ipv6") == "Down"

    wwan = _wan_interface_by_name(hub, "wwan")
    assert _wan_protocol_status(wwan, "ipv4") == "Down"
    assert _wan_protocol_status(wwan, "ipv6") == "Up"

    assert _wan_protocol_status(None, "ipv4") == "Unknown"

    hub.device_mac = "00:11:22:33:44:55"
    hub.device_info = {}
    hub.hass = object()
    sensor = WanStatusSensor(hub, "wan", {"ipv4", "ipv6"})

    assert sensor._attr_name == "Ethernet 1 status"
    assert sensor.unique_id == "glinet_sensor/00:11:22:33:44:55/wan_status_wan"
    assert sensor.native_value == "Up"
    assert sensor.extra_state_attributes == {
        "interface": "wan",
        "interface_name": "Ethernet 1",
        "requested_interface": "wan",
        "monitored_protocols": ["ipv4", "ipv6"],
        "ipv4_status": "Up",
        "ipv6_status": "Down",
        "status_v4": 0,
        "status_v6": 1,
    }

    sensor = WanStatusSensor(hub, "wan", {"ipv6"})
    assert sensor.native_value == "Down"

    unknown_sensor = WanStatusSensor(hub, "custom_wan", {"ipv4"})
    assert unknown_sensor._attr_name == "custom_wan status"


def test_sms_sensor_counts_only_unread_messages() -> None:
    from custom_components.glinet_router.entities.sensor import HUB_SENSORS
    from custom_components.glinet_router.models import SmsMessage

    desc = next(d for d in HUB_SENSORS if d.key == "sms_messages")

    unread = SmsMessage(message_id="1", phone_number="+44123", text="a", status=0)
    read = SmsMessage(message_id="2", phone_number="+44456", text="b", status=1)
    sent = SmsMessage(message_id="3", phone_number="+44789", text="c", status=2)

    hub = types.SimpleNamespace(
        sms_messages={"1": unread, "2": read, "3": sent},
    )

    assert desc.value_fn(hub) == 1
    attrs = desc.extra_attributes_fn(hub)
    assert attrs["unread_count"] == 1
    assert attrs["message_count"] == 3
    assert attrs["incoming_count"] == 2
    assert attrs["outgoing_count"] == 1


def test_sms_sensor_returns_zero_when_no_unread() -> None:
    from custom_components.glinet_router.entities.sensor import HUB_SENSORS
    from custom_components.glinet_router.models import SmsMessage

    desc = next(d for d in HUB_SENSORS if d.key == "sms_messages")

    read = SmsMessage(message_id="1", phone_number="+44123", text="a", status=1)
    sent = SmsMessage(message_id="2", phone_number="+44456", text="b", status=2)

    hub = types.SimpleNamespace(
        sms_messages={"1": read, "2": sent},
    )

    assert desc.value_fn(hub) == 0
    assert desc.extra_attributes_fn(hub)["unread_count"] == 0


def test_cellular_ip_sensors_are_enabled() -> None:
    from custom_components.glinet_router.entities.sensor import HUB_SENSORS, _sensor_is_enabled

    desc_v4 = next(d for d in HUB_SENSORS if d.key == "cellular_ipv4")
    desc_v6 = next(d for d in HUB_SENSORS if d.key == "cellular_ipv6")

    hub = types.SimpleNamespace(
        wan_status_monitors=None,
        kmwan_status={
            "interfaces": [
                {"interface": "wan"},
                {"interface": "modem_0001"},
            ]
        },
    )
    assert _sensor_is_enabled(hub, desc_v4) is True
    assert _sensor_is_enabled(hub, desc_v6) is True

    hub = types.SimpleNamespace(
        wan_status_monitors=None,
        kmwan_status={
            "interfaces": [
                {"interface": "wan"},
                {"interface": "wwan"},
            ]
        },
    )
    assert _sensor_is_enabled(hub, desc_v4) is False
    assert _sensor_is_enabled(hub, desc_v6) is False

    hub = types.SimpleNamespace(
        wan_status_monitors={"modem_0001:ipv4", "wan:ipv4"}, kmwan_status={}
    )
    assert _sensor_is_enabled(hub, desc_v4) is True
    assert _sensor_is_enabled(hub, desc_v6) is False

    hub = types.SimpleNamespace(
        wan_status_monitors={"modem_0001:ipv6", "wwan:ipv4"}, kmwan_status={}
    )
    assert _sensor_is_enabled(hub, desc_v4) is False
    assert _sensor_is_enabled(hub, desc_v6) is True


def test_get_cellular_ip_resolves_correctly() -> None:
    from custom_components.glinet_router.entities.sensor import _get_cellular_ip

    hub = types.SimpleNamespace(
        cellular_status={
            "modems": [
                {
                    "bus": "0001:01:00.0",
                    "network": {
                        "status": 0,
                        "ipv4": {
                            "gateway": "10.164.158.132",
                            "ip": "10.164.158.131",
                        },
                    },
                }
            ]
        }
    )

    assert _get_cellular_ip(hub, "ipv4") == "10.164.158.131"
    assert _get_cellular_ip(hub, "ipv6") is None

    hub = types.SimpleNamespace(
        cellular_status={
            "modems": [
                {
                    "bus": "0001:01:00.0",
                    "network": {
                        "status": 0,
                        "ipv4": {
                            "ip": "10.164.158.131",
                        },
                        "ipv6": {
                            "ip": "2001:db8::1",
                        },
                    },
                }
            ]
        }
    )

    assert _get_cellular_ip(hub, "ipv4") == "10.164.158.131"
    assert _get_cellular_ip(hub, "ipv6") == "2001:db8::1"

    hub = types.SimpleNamespace(
        cellular_status={
            "modems": [
                {
                    "bus": "0001:01:00.0",
                    "network_interface": "modem_0001_s1",
                    "ipv4": {
                        "ip": "10.77.58.41",
                        "gateway": "10.77.58.42",
                        "netmask": "255.255.255.252",
                    },
                    "ipv6": {
                        "ip": "2001:db8::42",
                    },
                }
            ]
        }
    )

    assert _get_cellular_ip(hub, "ipv4") == "10.77.58.41"
    assert _get_cellular_ip(hub, "ipv6") == "2001:db8::42"


async def test_legacy_cellular_sensors_registered_only_on_firmware_4_8() -> None:
    from custom_components.glinet_router.entities.sensor import HUB_SENSORS

    keys = {d.key for d in HUB_SENSORS}
    for legacy in ("cellular_signal", "cellular_rssi", "cellular_network"):
        assert legacy in keys
    for expected in (
        "cellular_band",
        "cellular_rsrp",
        "cellular_rsrq",
        "cellular_sinr",
        "cellular_apn",
    ):
        assert expected in keys


async def test_legacy_cellular_sensors_enabled_only_on_firmware_4_8() -> None:
    from custom_components.glinet_router.entities.sensor import HUB_SENSORS, _sensor_is_enabled

    legacy_descriptions = [
        next(d for d in HUB_SENSORS if d.key == key)
        for key in ("cellular_signal", "cellular_rssi", "cellular_network")
    ]

    hub_48 = types.SimpleNamespace(
        wan_status_monitors=None,
        kmwan_status={"interfaces": []},
        is_firmware_4_9_or_above=False,
        feature_enabled=lambda feature: True,
    )
    for description in legacy_descriptions:
        assert _sensor_is_enabled(hub_48, description) is True

    hub_49 = types.SimpleNamespace(
        wan_status_monitors=None,
        kmwan_status={"interfaces": []},
        is_firmware_4_9_or_above=True,
        feature_enabled=lambda feature: True,
    )
    for description in legacy_descriptions:
        assert _sensor_is_enabled(hub_49, description) is False

    hub_48_feature_off = types.SimpleNamespace(
        wan_status_monitors=None,
        kmwan_status={"interfaces": []},
        is_firmware_4_9_or_above=False,
        feature_enabled=lambda feature: False,
    )
    for description in legacy_descriptions:
        assert _sensor_is_enabled(hub_48_feature_off, description) is False


async def test_legacy_cellular_sensors_resolve_values_from_firmware_4_8_payload() -> None:
    from custom_components.glinet_router.entities.sensor import HUB_SENSORS

    legacy_keys = {"cellular_signal", "cellular_rssi", "cellular_network"}
    descriptions = {d.key: d for d in HUB_SENSORS if d.key in legacy_keys}

    hub = types.SimpleNamespace(
        cellular_status={
            "modems": [
                {
                    "bus": "0001:01:00.0",
                    "slot": "1",
                    "signal": 4,
                    "network_type": "LTE",
                    "simcard": {
                        "apn": "internet",
                        "carrier": "Vodafone",
                        "band": "LTE Band 4",
                        "signal": {
                            "rssi": -71,
                            "rsrp": -100,
                            "rsrq": -8,
                            "sinr": 17,
                            "strength": 4,
                            "network_type": "LTE",
                        },
                    },
                }
            ]
        }
    )

    assert descriptions["cellular_signal"].value_fn(hub) == -71
    assert descriptions["cellular_rssi"].value_fn(hub) == -71
    assert descriptions["cellular_network"].value_fn(hub) == "Vodafone"


def test_cellular_rsrp_remains_enabled_on_firmware_4_9() -> None:
    from custom_components.glinet_router.entities.sensor import HUB_SENSORS, _sensor_is_enabled

    desc_rsrp = next(d for d in HUB_SENSORS if d.key == "cellular_rsrp")
    desc_band = next(d for d in HUB_SENSORS if d.key == "cellular_band")
    desc_apn = next(d for d in HUB_SENSORS if d.key == "cellular_apn")

    hub_49_enabled = types.SimpleNamespace(
        wan_status_monitors=None,
        kmwan_status={"interfaces": []},
        is_firmware_4_9_or_above=True,
        feature_enabled=lambda feature: True,
    )
    assert _sensor_is_enabled(hub_49_enabled, desc_rsrp) is True
    assert _sensor_is_enabled(hub_49_enabled, desc_band) is True
    assert _sensor_is_enabled(hub_49_enabled, desc_apn) is True

    hub_49_disabled = types.SimpleNamespace(
        wan_status_monitors=None,
        kmwan_status={"interfaces": []},
        is_firmware_4_9_or_above=True,
        feature_enabled=lambda feature: False,
    )
    assert _sensor_is_enabled(hub_49_disabled, desc_rsrp) is False
    assert _sensor_is_enabled(hub_49_disabled, desc_band) is False
    assert _sensor_is_enabled(hub_49_disabled, desc_apn) is False


def test_cellular_status_resolves_to_active_slot_on_firmware_4_9() -> None:
    from custom_components.glinet_router.entities.sensor import (
        WanStatusSensor,
        _wan_interface_by_name,
    )

    hub = types.SimpleNamespace(
        device_mac="00:11:22:33:44:55",
        device_info={},
        hass=object(),
        is_firmware_4_9_or_above=True,
        kmwan_status={
            "interfaces": [
                {"interface": "wan", "status_v4": 0, "status_v6": 1},
                {"interface": "wwan", "status_v4": 1, "status_v6": 0},
                {"interface": "modem_0001", "status_v4": 1, "status_v6": 1},
                {"interface": "modem_0001_s1", "status_v4": 0, "status_v6": 1},
                {"interface": "modem_0001_s2", "status_v4": 1, "status_v6": 1},
            ]
        },
    )

    resolved = _wan_interface_by_name(hub, "modem_0001")
    assert resolved is not None
    assert resolved["interface"] == "modem_0001_s1"
    assert resolved["status_v4"] == 0

    sensor = WanStatusSensor(hub, "modem_0001", {"ipv4", "ipv6"})
    assert sensor.native_value == "Up"
    attrs = sensor.extra_state_attributes
    assert attrs["interface"] == "modem_0001_s1"
    assert attrs["requested_interface"] == "modem_0001"
    assert attrs["status_v4"] == 0
    assert attrs["ipv4_status"] == "Up"
    assert attrs["ipv6_status"] == "Down"


def test_cellular_status_falls_back_to_first_slot_when_none_up_on_firmware_4_9() -> None:
    from custom_components.glinet_router.entities.sensor import (
        WanStatusSensor,
        _wan_interface_by_name,
    )

    hub = types.SimpleNamespace(
        device_mac="00:11:22:33:44:55",
        device_info={},
        hass=object(),
        is_firmware_4_9_or_above=True,
        kmwan_status={
            "interfaces": [
                {"interface": "modem_0001", "status_v4": 1, "status_v6": 1},
                {"interface": "modem_0001_s1", "status_v4": 1, "status_v6": 1},
                {"interface": "modem_0001_s2", "status_v4": 1, "status_v6": 1},
            ]
        },
    )

    resolved = _wan_interface_by_name(hub, "modem_0001")
    assert resolved is not None
    assert resolved["interface"] == "modem_0001_s1"

    sensor = WanStatusSensor(hub, "modem_0001", {"ipv4", "ipv6"})
    assert sensor.native_value == "Down"


def test_cellular_status_keeps_aggregate_on_firmware_4_8() -> None:
    from custom_components.glinet_router.entities.sensor import (
        WanStatusSensor,
        _wan_interface_by_name,
    )

    hub = types.SimpleNamespace(
        device_mac="00:11:22:33:44:55",
        device_info={},
        hass=object(),
        is_firmware_4_9_or_above=False,
        kmwan_status={
            "interfaces": [
                {"interface": "modem_0001", "status_v4": 0, "status_v6": 1},
            ]
        },
    )

    resolved = _wan_interface_by_name(hub, "modem_0001")
    assert resolved is not None
    assert resolved["interface"] == "modem_0001"
    assert resolved["status_v4"] == 0

    sensor = WanStatusSensor(hub, "modem_0001", {"ipv4", "ipv6"})
    assert sensor.native_value == "Up"
    attrs = sensor.extra_state_attributes
    assert attrs["interface"] == "modem_0001"
    assert attrs["requested_interface"] == "modem_0001"


def test_normalise_traffic_config_4_8_with_one_sim_present() -> None:
    from custom_components.glinet_router.hub import _normalise_traffic_config

    response = {
        "save_to_flash": True,
        "sim1_traffic_total": 1234,
        "sim1_limit": {
            "enable": True,
            "threshold": 500,
            "unit": "MB",
            "reset_period": "month",
            "day": 15,
            "hour": 4,
        },
        "sim2_traffic_total": 0,
        "sim2_limit": {
            "enable": False,
            "threshold": 0,
            "unit": "GB",
            "reset_period": "month",
            "day": 1,
            "hour": 0,
        },
    }

    sims = _normalise_traffic_config(response, is_firmware_4_9=False)

    assert len(sims) == 2
    sim1, sim2 = sims
    assert sim1["slot"] == 1
    assert sim1["sim_type"] == 0
    assert sim1["traffic_total"] == 1234
    assert sim1["present"] is True
    assert sim1["limit_enabled"] is True
    assert sim1["threshold"] == 500
    assert sim1["unit"] == "MB"
    assert sim1["reset_period"] == "month"
    assert sim1["day"] == 15
    assert sim1["hour"] == 4
    assert sim1["save_to_flash"] is True
    assert isinstance(sim1["days_until_reset"], int)
    assert sim1["days_until_reset"] >= 0

    assert sim2["slot"] == 2
    assert sim2["traffic_total"] == 0
    assert sim2["present"] is False
    assert sim2["limit_enabled"] is False
    assert sim2["days_until_reset"] is None


def test_normalise_traffic_config_4_8_when_no_sim_has_traffic() -> None:
    from custom_components.glinet_router.hub import _normalise_traffic_config

    response = {
        "save_to_flash": False,
        "sim1_traffic_total": 0,
        "sim2_traffic_total": 0,
    }

    sims = _normalise_traffic_config(response, is_firmware_4_9=False)

    assert len(sims) == 2
    assert all(sim["present"] is False for sim in sims)
    assert all(sim["days_until_reset"] is None for sim in sims)
    assert all(sim["save_to_flash"] is False for sim in sims)


def test_normalise_traffic_config_4_8_tolerates_missing_limit_block() -> None:
    from custom_components.glinet_router.hub import _normalise_traffic_config

    response = {
        "sim1_traffic_total": 42,
    }

    sims = _normalise_traffic_config(response, is_firmware_4_9=False)

    sim1 = sims[0]
    assert sim1["slot"] == 1
    assert sim1["traffic_total"] == 42
    assert sim1["limit_enabled"] is False
    assert sim1["threshold"] is None
    assert sim1["unit"] is None
    assert sim1["reset_period"] is None


def test_normalise_traffic_config_4_9_with_traffic_and_limit() -> None:
    from custom_components.glinet_router.hub import _normalise_traffic_config

    response = {
        "save_to_flash": True,
        "traffic": [
            {"slot": 1, "type": 0, "traffic_total": 5000},
            {"slot": 2, "type": 0, "traffic_total": 0},
        ],
        "limit": [
            {
                "slot": 1,
                "type": 0,
                "enable": True,
                "threshold": 10,
                "unit": "GB",
                "reset_period": "month",
                "day": 5,
                "hour": 12,
            }
        ],
    }

    sims = _normalise_traffic_config(response, is_firmware_4_9=True)

    sim1, sim2 = sims
    assert sim1["slot"] == 1
    assert sim1["sim_type"] == 0
    assert sim1["traffic_total"] == 5000
    assert sim1["present"] is True
    assert sim1["limit_enabled"] is True
    assert sim1["threshold"] == 10
    assert sim1["unit"] == "GB"
    assert sim1["reset_period"] == "month"
    assert sim1["day"] == 5
    assert sim1["hour"] == 12
    assert sim1["save_to_flash"] is True

    assert sim2["slot"] == 2
    assert sim2["present"] is False
    assert sim2["limit_enabled"] is False
    assert sim2["threshold"] is None


def test_normalise_traffic_config_4_9_handles_only_traffic_array() -> None:
    from custom_components.glinet_router.hub import _normalise_traffic_config

    response = {
        "save_to_flash": False,
        "traffic": [
            {"slot": 1, "type": 0, "traffic_total": 100},
        ],
    }

    sims = _normalise_traffic_config(response, is_firmware_4_9=True)

    assert len(sims) == 1
    sim1 = sims[0]
    assert sim1["slot"] == 1
    assert sim1["traffic_total"] == 100
    assert sim1["present"] is True
    assert sim1["limit_enabled"] is False
    assert sim1["save_to_flash"] is False


def test_normalise_traffic_config_4_9_handles_esim_type() -> None:
    from custom_components.glinet_router.hub import _normalise_traffic_config

    response = {
        "traffic": [
            {"slot": 1, "type": 1, "traffic_total": 2500},
        ],
    }

    sims = _normalise_traffic_config(response, is_firmware_4_9=True)

    assert sims[0]["sim_type"] == 1
    assert sims[0]["present"] is True


def test_normalise_traffic_config_returns_empty_for_non_dict() -> None:
    from custom_components.glinet_router.hub import _normalise_traffic_config

    assert _normalise_traffic_config(None, is_firmware_4_9=True) == []
    assert _normalise_traffic_config("not-a-dict", is_firmware_4_9=False) == []


def test_compute_days_until_reset_disabled_returns_none() -> None:
    from custom_components.glinet_router.hub import _compute_days_until_reset

    record = {
        "limit_enabled": False,
        "reset_period": "month",
        "day": 1,
        "hour": 0,
        "month": 1,
    }
    assert _compute_days_until_reset(record) is None


def test_compute_days_until_reset_unknown_period_returns_none() -> None:
    from custom_components.glinet_router.hub import _compute_days_until_reset

    record = {
        "limit_enabled": True,
        "reset_period": "fortnight",
        "day": 1,
        "hour": 0,
        "month": 1,
    }
    assert _compute_days_until_reset(record) is None


def test_compute_days_until_reset_month_anchor_in_future() -> None:
    from datetime import datetime

    from custom_components.glinet_router.hub import _compute_days_until_reset

    now = datetime.now()
    target_day = 5 if now.day < 5 else 20
    record = {
        "limit_enabled": True,
        "reset_period": "month",
        "day": target_day,
        "hour": 0,
        "month": now.month,
    }
    result = _compute_days_until_reset(record)
    assert isinstance(result, int)
    assert 0 <= result <= 31


def test_cellular_traffic_sensor_value_fns_return_per_slot_values() -> None:
    from custom_components.glinet_router.entities.sensor import (
        CellularTrafficSensor,
        _build_cellular_traffic_descriptions,
        _get_traffic_sim,
        _traffic_sim_present,
    )

    hub = types.SimpleNamespace(
        device_mac="00:11:22:33:44:55",
        device_info={},
        hass=object(),
        traffic_sim_data={
            1: {
                "slot": 1,
                "sim_type": 0,
                "traffic_total": 4096,
                "limit_enabled": True,
                "threshold": 10,
                "unit": "GB",
                "reset_period": "month",
                "day": 1,
                "hour": 0,
                "month": 1,
                "save_to_flash": True,
                "present": True,
                "days_until_reset": 12,
            },
            2: {
                "slot": 2,
                "sim_type": 0,
                "traffic_total": 0,
                "limit_enabled": False,
                "threshold": None,
                "unit": None,
                "reset_period": None,
                "day": None,
                "hour": None,
                "month": None,
                "save_to_flash": False,
                "present": False,
                "days_until_reset": None,
            },
        },
    )

    assert _traffic_sim_present(hub, 1) is True
    assert _get_traffic_sim(hub, 1)["traffic_total"] == 4096
    assert _traffic_sim_present(hub, 2) is False

    descs = _build_cellular_traffic_descriptions(1, 0)
    by_key = {d.key: d for d in descs}
    assert by_key["traffic_total"].value_fn(hub, 1, 0) == 4096
    assert by_key["days_until_reset"].value_fn(hub, 1, 0) == 12
    assert by_key["data_limit"].value_fn(hub, 1, 0) == 10

    for d in descs:
        assert d.value_fn(hub, 2, 0) is None

    traffic_sensor = CellularTrafficSensor(hub=hub, entity_description=by_key["traffic_total"])
    assert traffic_sensor.unique_id == (
        "glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_1_0_traffic_total"
    )
    assert traffic_sensor._attr_name == "SIM 1 Traffic total"
    assert traffic_sensor.native_value == 4096
    assert traffic_sensor.available is True

    data_limit_sensor = CellularTrafficSensor(hub=hub, entity_description=by_key["data_limit"])
    attrs = data_limit_sensor.extra_state_attributes
    assert attrs["slot"] == 1
    assert attrs["sim_type"] == 0
    assert attrs["limit_enabled"] is True
    assert attrs["unit"] == "GB"
    assert attrs["reset_period"] == "month"
    assert attrs["day"] == 1
    assert attrs["hour"] == 0
    assert attrs["save_to_flash"] is True

    slot2_sensor = CellularTrafficSensor(
        hub=hub,
        entity_description=_build_cellular_traffic_descriptions(2, 0)[0],
    )
    assert slot2_sensor.available is False
    assert slot2_sensor.native_value is None


def test_cellular_traffic_sensor_unavailable_when_sim_missing() -> None:
    from custom_components.glinet_router.entities.sensor import (
        CellularTrafficSensor,
        _build_cellular_traffic_descriptions,
    )

    hub = types.SimpleNamespace(
        device_mac="AA:BB:CC:DD:EE:FF",
        device_info={},
        hass=object(),
        traffic_sim_data={},
    )

    descs = _build_cellular_traffic_descriptions(3, 0)
    sensor = CellularTrafficSensor(hub=hub, entity_description=descs[0])
    assert sensor.available is False
    assert sensor.native_value is None


async def test_register_cellular_limit_sensors_creates_when_limit_enabled() -> None:
    from custom_components.glinet_router.entities.sensor import (
        CellularTrafficSensor,
    )

    added: list = []

    async def _add(entities, _update=True):
        for entity in entities:
            added.append(entity.unique_id)

    hub = types.SimpleNamespace(
        device_mac="00:11:22:33:44:55",
        device_info={},
        hass=object(),
        traffic_sim_data={
            1: {
                "slot": 1,
                "sim_type": 0,
                "traffic_total": 100,
                "limit_enabled": True,
                "threshold": 1000,
                "unit": "MB",
                "reset_period": "month",
                "day": 1,
                "hour": 0,
                "month": 0,
                "present": True,
                "days_until_reset": 5,
            },
        },
    )

    def _feature_enabled(name):
        return name == "cellular"

    hub.feature_enabled = _feature_enabled

    from custom_components.glinet_router.entities.sensor import (
        _build_cellular_traffic_descriptions,
    )

    cellular_tracked: set = set()

    def _register_cellular_limit_sensors():
        if not hub.feature_enabled("cellular"):
            return
        new_entities = []
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
                if candidate.unique_id in cellular_tracked:
                    continue
                cellular_tracked.add(candidate.unique_id)
                new_entities.append(candidate)
        if new_entities:
            import asyncio

            asyncio.get_event_loop().create_task(_add(new_entities))

    _register_cellular_limit_sensors()

    import asyncio

    await asyncio.sleep(0.01)

    assert any("data_limit" in uid for uid in added)
    assert any("days_until_reset" in uid for uid in added)


async def test_register_cellular_limit_sensors_recreates_after_cleanup() -> None:
    from unittest.mock import MagicMock

    from custom_components.glinet_router.entities import sensor as sensor_module

    registry_store: dict[str, MagicMock] = {}

    def _make_entry(unique_id: str) -> MagicMock:
        entry = MagicMock()
        entry.unique_id = unique_id
        entry.entity_id = f"sensor.{unique_id.split('/')[-1]}"
        registry_store[unique_id] = entry
        return entry

    def _async_get(_hass):
        return None

    def _async_entries(_registry, _eid):
        return list(registry_store.values())

    sensor_module.er.async_get = _async_get
    sensor_module.er.async_entries_for_config_entry = _async_entries

    hub = MagicMock()
    hub.feature_enabled.return_value = True
    hub.device_mac = "00:11:22:33:44:55"
    hub.hass = MagicMock()
    hub._entry.entry_id = "test_entry"
    hub.traffic_sim_data = {
        1: {
            "slot": 1,
            "sim_type": 0,
            "present": True,
            "limit_enabled": True,
            "traffic_total": 100,
        },
    }

    added: list = []

    def _capture(entities):
        for entity in entities:
            added.append(entity.unique_id)
            _make_entry(entity.unique_id)

    callback = sensor_module._make_register_cellular_limit_sensors_callback(hub, _capture)

    _make_entry("glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_1_0_traffic_total")
    callback()
    assert any("data_limit" in uid for uid in added)
    assert any("days_until_reset" in uid for uid in added)

    added.clear()
    callback()
    assert added == []

    for uid in list(registry_store):
        if "data_limit" in uid or "days_until_reset" in uid:
            registry_store.pop(uid)
    callback()
    assert any("data_limit" in uid for uid in added)
    assert any("days_until_reset" in uid for uid in added)


def test_cellular_traffic_data_limit_sensors_require_limit_enabled() -> None:
    from custom_components.glinet_router.entities.sensor import (
        _build_cellular_traffic_descriptions,
    )

    descs = _build_cellular_traffic_descriptions(1, 0)
    by_key = {d.key: d for d in descs}
    assert by_key["traffic_total"].requires_limit is False
    assert by_key["days_until_reset"].requires_limit is True
    assert by_key["data_limit"].requires_limit is True
