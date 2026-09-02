from __future__ import annotations

import types
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.glinet_router.const import (
    CONF_ADD_ALL_DEVICES,
    CONF_CLEANUP_DEVICES,
    CONF_ENABLED_FEATURES,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    CONF_WAN_STATUS_MONITORS,
    FEATURE_REPEATER,
    FEATURE_WG_CLIENT,
    FEATURE_WG_SERVER,
)
from custom_components.glinet_router.hub import GLinetHub, utcnow
from custom_components.glinet_router.models import ClientDeviceInfo, RepeaterState, RepeaterStatus


def _hub_with_devices() -> GLinetHub:
    hub = GLinetHub.__new__(GLinetHub)
    hub._options = {"consider_home": 0}
    hub._settings = {}
    hub._factory_mac = "00:00:00:00:00:00"
    hub._host = "192.168.8.1"
    hub._devices = {"aa:bb:cc:dd:ee:ff": ClientDeviceInfo("aa:bb:cc:dd:ee:ff")}
    hub._devices["aa:bb:cc:dd:ee:ff"].apply_update({"online": True})
    hub._all_connected_clients = {}
    hub._invoke_api = _invoke_api_empty_clients
    hub._api = types.SimpleNamespace(clients=types.SimpleNamespace(get_online=object()))
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = object()
    return hub


async def _invoke_api_empty_clients(_: Any) -> dict[str, dict[str, Any]]:
    return {}


def test_router_traffic_sensors_sum_all_connected_clients() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._devices = {}
    hub._all_connected_clients = {
        "aa:bb:cc:dd:ee:ff": {"rx": 10, "tx": 20, "total_rx": 100, "total_tx": 200},
        "11:22:33:44:55:66": {"rx": 30, "tx": 40, "total_rx": 300, "total_tx": 400},
    }

    assert hub.current_traffic_download == 40
    assert hub.current_traffic_upload == 60
    assert hub.total_traffic_download == 400
    assert hub.total_traffic_upload == 600


def test_router_traffic_includes_untracked_devices() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._devices = {"aa:bb:cc:dd:ee:ff": ClientDeviceInfo("aa:bb:cc:dd:ee:ff")}
    hub._all_connected_clients = {
        "aa:bb:cc:dd:ee:ff": {"rx": 10, "tx": 20, "total_rx": 100, "total_tx": 200},
        "11:22:33:44:55:66": {"rx": 5, "tx": 8, "total_rx": 50, "total_tx": 80},
    }

    assert hub.current_traffic_download == 15
    assert hub.current_traffic_upload == 28
    assert hub.total_traffic_download == 150
    assert hub.total_traffic_upload == 280


async def test_fetch_connected_devices_marks_existing_devices_away_on_empty_client_list(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_dispatcher_send(_: Any, event: str) -> None:
        calls.append(event)

    import custom_components.glinet_router.hub as hub_module

    monkeypatch.setattr(hub_module, "async_dispatcher_send", fake_dispatcher_send)
    hub = _hub_with_devices()

    await hub.fetch_connected_devices()

    assert hub._devices["aa:bb:cc:dd:ee:ff"].is_connected is False
    assert calls == ["glinet_router-device-update-00:00:00:00:00:00"]


async def test_fetch_tailscale_state_treats_timeout_as_optional() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    hub._tailscale_config = {"enabled": True}
    hub._tailscale_connection = True

    async def invoke_optional_api(_: Any) -> None:
        return None

    hub._invoke_optional_api = invoke_optional_api
    hub._api = types.SimpleNamespace(tailscale=types.SimpleNamespace(get_details=object()))

    await hub.fetch_tailscale_state()

    assert hub._tailscale_config == {}
    assert hub._tailscale_connection is None


async def test_fetch_cellular_status_merges_modem_info_and_status() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._cached_modem_info = None
    hub._settings = {}
    hub._cellular_status = {}
    hub._default_modem_bus = None
    responses = [
        {"modems": [{"bus": "1-1", "sms_support": True, "name": "Quectel"}]},
        {"modems": [{"bus": "1-1", "simcard": {"carrier": "CMCC"}}]},
    ]

    async def invoke_optional_api(_: Any) -> dict[str, Any]:
        return responses.pop(0)

    hub._invoke_optional_api = invoke_optional_api
    hub._api = types.SimpleNamespace(
        modem=types.SimpleNamespace(get_info=object(), get_status=object())
    )

    await hub.fetch_cellular_status()

    assert hub.default_modem_bus == "1-1"

    assert hub.cellular_status["modems"] == [
        {
            "bus": "1-1",
            "sms_support": True,
            "name": "Quectel",
            "simcard": {"carrier": "CMCC"},
        }
    ]


async def test_fetch_cellular_status_extracts_apn() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._cached_modem_info = None
    hub._settings = {}
    hub._cellular_status = {}
    responses = [
        {"modems": [{"bus": "1-1"}]},
        {"modems": [{"bus": "1-1", "simcard": {"apn": "test.apn"}}]},
    ]

    async def invoke_optional_api(_: Any) -> dict[str, Any]:
        return responses.pop(0)

    hub._invoke_optional_api = invoke_optional_api
    hub._api = types.SimpleNamespace(
        modem=types.SimpleNamespace(get_info=object(), get_status=object())
    )

    await hub.fetch_cellular_status()

    assert hub.cellular_status["modems"][0]["simcard"]["apn"] == "test.apn"


async def test_fetch_cellular_status_fetches_sim_config_on_firmware_4_9() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._cached_modem_info = None
    hub._settings = {}
    hub._cellular_status = {}
    hub._default_modem_bus = None
    hub._sw_version = "4.9.0"
    hub._api = None
    hub.is_firmware_4_9_or_above = True

    info_response = {
        "modems": [{"bus": "0001:01:00.0", "iccid": "8944200204977051694F", "slot": "1"}]
    }
    status_response = {
        "modems": [
            {
                "bus": "0001:01:00.0",
                "slot": "1",
                "iccid": "8944200204977051694F",
                "simcard": {"iccid": "8944200204977051694F"},
            }
        ]
    }
    sim_config_response = {
        "8944200204977051694F": {
            "manual": True,
            "username": "",
            "pincode": "",
            "ip_type": 1,
            "cid": 1,
            "roaming": False,
            "apn": "mob.asm.net",
            "password": "",
            "auth": "NONE",
        }
    }

    sim_calls: list[str] = []
    info_calls: list[Any] = []
    status_calls: list[Any] = []

    async def invoke_optional_api(callable_: Any) -> Any:
        callable_()
        if callable_ is hub._api.modem.get_info:
            info_calls.append(callable_)
            return info_response
        if callable_ is hub._api.modem.get_status:
            status_calls.append(callable_)
            return status_response
        if callable_.__name__ == "<lambda>" or "get_sim_config" in str(callable_):
            sim_calls.append(str(callable_.__closure__[0].cell_contents))
            return sim_config_response
        return None

    hub._invoke_optional_api = invoke_optional_api
    hub._api = types.SimpleNamespace(
        modem=types.SimpleNamespace(
            get_info=lambda: info_response,
            get_status=lambda: status_response,
            get_sim_config=lambda bus: sim_config_response,
        )
    )

    await hub.fetch_cellular_status()

    modem = hub.cellular_status["modems"][0]
    assert modem["simcard"]["apn"] == "mob.asm.net"
    assert sim_calls == ["0001:01:00.0"]


async def test_fetch_cellular_status_keeps_4_8_apn_source() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._cached_modem_info = None
    hub._settings = {}
    hub._cellular_status = {}
    hub._default_modem_bus = None
    hub._sw_version = "4.8.3"
    hub._api = None
    hub.is_firmware_4_9_or_above = False

    info_response = {"modems": [{"bus": "0001:01:00.0", "iccid": "ICCID-1"}]}
    status_response = {
        "modems": [
            {
                "bus": "0001:01:00.0",
                "iccid": "ICCID-1",
                "simcard": {"iccid": "ICCID-1", "apn": "legacy.apn"},
            }
        ]
    }

    sim_calls: list[Any] = []

    async def invoke_optional_api(callable_: Any) -> Any:
        if callable_.__name__ == "<lambda>" or "get_sim_config" in str(callable_):
            sim_calls.append(callable_)
        return None

    hub._invoke_optional_api = invoke_optional_api
    hub._api = types.SimpleNamespace(
        modem=types.SimpleNamespace(
            get_info=lambda: info_response,
            get_status=lambda: status_response,
            get_sim_config=lambda bus: None,
        )
    )

    queue = iter([info_response, status_response])

    async def invoke(_: Any) -> Any:
        return next(queue, None)

    hub._invoke_optional_api = invoke

    await hub.fetch_cellular_status()

    modem = hub.cellular_status["modems"][0]
    assert sim_calls == []
    assert modem["simcard"]["apn"] == "legacy.apn"


async def test_send_sms_uses_default_modem_bus() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    hub._default_modem_bus = "1-1"
    hub.fetch_sms_messages = _noop
    sent: list[tuple[str, str, str]] = []

    class ModemModule:
        async def send_sms(self, bus: str, recipient: str, text: str) -> dict[str, Any]:
            sent.append((bus, recipient, text))
            return {"response": "ok"}

    class RouterApi:
        modem = ModemModule()

    async def invoke_optional_api(api_callable: Any) -> dict[str, Any]:
        return await api_callable()

    hub._api = RouterApi()
    hub._invoke_optional_api = invoke_optional_api

    await hub.send_sms("+441234567890", "hello")

    assert sent == [("1-1", "+441234567890", "hello")]


def test_traffic_config_bus_uses_modem_record_bus_when_present() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._modems = {"1-1:00.0": {"bus": "0001:01:00.0"}}
    hub._default_modem_bus = "1-1:00.0"

    assert hub._traffic_config_bus() == "0001:01:00.0"


def test_traffic_config_bus_uses_short_bus_from_4_9_modem_record() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._modems = {
        "modem_0001_s1": {"bus": "0001", "slot": 1},
        "modem_0001_s2": {"bus": "0001", "slot": 2},
    }
    hub._default_modem_bus = "cpu"
    hub._sw_version = "4.9.0"

    assert hub._traffic_config_bus() == "0001"


def test_traffic_config_bus_falls_back_to_default_modem_bus() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._modems = {}
    hub._default_modem_bus = "1-1:00.0"

    assert hub._traffic_config_bus() == "1-1:00.0"


def test_traffic_config_bus_returns_none_when_no_bus_known() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._modems = {}
    hub._default_modem_bus = None

    assert hub._traffic_config_bus() is None


async def test_fetch_all_data_skips_disabled_features(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: [FEATURE_REPEATER]}
    hub._tailscale_config = {}
    hub._tailscale_connection = True
    hub._cellular_status = {"signal": 10}
    hub._modems = {"1-1": {}}
    hub._saved_networks = [{"ssid": "old"}]
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._host = "192.168.8.1"
    hub._last_upgrade_check = None
    hub.hass = object()

    called: list[str] = []

    async def fake_fetch_system_status() -> None:
        called.append("system")

    async def fake_fetch_kmwan_status() -> None:
        called.append("kmwan")

    async def fake_fetch_connected_devices() -> None:
        called.append("clients")

    async def fake_fetch_wifi_interfaces() -> None:
        called.append("wifi")

    async def fake_fetch_wireguard_clients() -> None:
        called.append("wg_client")

    async def fake_fetch_wg_server_status() -> None:
        called.append("wg_server")

    async def fake_fetch_repeater_status() -> None:
        called.append("repeater_status")

    async def fake_fetch_repeater_config() -> None:
        called.append("repeater_config")

    async def fake_fetch_saved_networks() -> None:
        called.append("saved_networks")

    async def fake_fetch_fan_status() -> None:
        called.append("fan")

    async def fake_fetch_led_status() -> None:
        called.append("led")

    hub.fetch_system_status = fake_fetch_system_status
    hub.fetch_kmwan_status = fake_fetch_kmwan_status
    hub.fetch_connected_devices = fake_fetch_connected_devices
    hub.fetch_wifi_interfaces = fake_fetch_wifi_interfaces
    hub.fetch_wireguard_clients = fake_fetch_wireguard_clients
    hub.fetch_wg_server_status = fake_fetch_wg_server_status
    hub.fetch_repeater_status = fake_fetch_repeater_status
    hub.fetch_repeater_config = fake_fetch_repeater_config
    hub.fetch_saved_networks = fake_fetch_saved_networks
    hub.fetch_fan_status = fake_fetch_fan_status
    hub.refresh_session_token = _noop

    hub.fetch_led_status = fake_fetch_led_status
    await hub.fetch_all_data()

    assert called == [
        "system",
        "kmwan",
        "clients",
        "wifi",
        "fan",
        "led",
        "repeater_status",
        "repeater_config",
        "saved_networks",
    ]
    assert hub._tailscale_config == {}
    assert hub._tailscale_connection is None
    assert hub._cellular_status == {}
    assert hub._modems == {}


async def test_fetch_all_data_runs_tasks_in_parallel_when_enabled(
    monkeypatch,
) -> None:
    import asyncio

    from custom_components.glinet_router.const import CONF_PARALLEL_REQUESTS

    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: [], CONF_PARALLEL_REQUESTS: True}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._host = "192.168.8.1"
    hub._last_upgrade_check = None
    hub.hass = object()
    hub.refresh_session_token = _noop

    started: list[str] = []
    completed: list[str] = []
    events = asyncio.Event()

    async def make_slow_fetch(name: str) -> Any:
        async def _run() -> None:
            started.append(name)
            await events.wait()
            completed.append(name)

        return _run

    async def fake_fetch_system_status() -> None:
        started.append("system")
        await events.wait()
        completed.append("system")

    async def fake_fetch_kmwan_status() -> None:
        started.append("kmwan")
        await events.wait()
        completed.append("kmwan")

    async def fake_fetch_connected_devices() -> None:
        started.append("clients")
        await events.wait()
        completed.append("clients")

    async def fake_fetch_wifi_interfaces() -> None:
        started.append("wifi")
        await events.wait()
        completed.append("wifi")

    async def fake_fetch_fan_status() -> None:
        started.append("fan")
        await events.wait()
        completed.append("fan")

    async def fake_fetch_led_status() -> None:
        started.append("led")
        await events.wait()
        completed.append("led")

    hub.fetch_system_status = fake_fetch_system_status
    hub.fetch_kmwan_status = fake_fetch_kmwan_status
    hub.fetch_connected_devices = fake_fetch_connected_devices
    hub.fetch_wifi_interfaces = fake_fetch_wifi_interfaces
    hub.fetch_fan_status = fake_fetch_fan_status
    hub.fetch_led_status = fake_fetch_led_status

    async def _release() -> None:
        await asyncio.sleep(0)
        events.set()

    release_task = asyncio.create_task(_release())
    await hub.fetch_all_data()
    await release_task

    assert set(started) == {"system", "kmwan", "clients", "wifi", "fan", "led"}
    assert completed == []


async def test_fetch_all_data_runs_tasks_sequentially_by_default(
    monkeypatch,
) -> None:
    import asyncio

    from custom_components.glinet_router.const import CONF_PARALLEL_REQUESTS

    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {
        CONF_ENABLED_FEATURES: [],
        CONF_PARALLEL_REQUESTS: False,
    }
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._host = "192.168.8.1"
    hub._last_upgrade_check = None
    hub.hass = object()
    hub.refresh_session_token = _noop

    order: list[str] = []
    started: dict[str, asyncio.Event] = {}
    completed: dict[str, asyncio.Event] = {}

    async def _ordered_fetch(name: str) -> None:
        order.append(f"{name}:start")
        started[name].set()
        await completed[name].wait()
        order.append(f"{name}:end")

    for name in (
        "system",
        "kmwan",
        "clients",
        "wifi",
        "fan",
        "led",
    ):
        started[name] = asyncio.Event()
        completed[name] = asyncio.Event()
        setattr(
            hub,
            f"fetch_{name.replace('clients', 'connected_devices').replace('led', 'led_status')}",
            _ordered_fetch(name),
        )

    expected_names = [
        "system_status",
        "kmwan_status",
        "connected_devices",
        "wifi_interfaces",
        "fan_status",
        "led_status",
    ]
    for name, attr in zip(
        ("system", "kmwan", "clients", "wifi", "fan", "led"),
        expected_names,
        strict=True,
    ):
        setattr(hub, f"fetch_{attr}", _ordered_fetch(name))

    async def _drive() -> None:
        for name in ("system", "kmwan", "clients", "wifi", "fan", "led"):
            await started[name].wait()
            completed[name].set()

    drive_task = asyncio.create_task(_drive())
    await hub.fetch_all_data()
    await drive_task

    expected_order = []
    for name in ("system", "kmwan", "clients", "wifi", "fan", "led"):
        expected_order.append(f"{name}:start")
        expected_order.append(f"{name}:end")
    assert order == expected_order


def test_parallel_requests_property_default() -> None:
    from custom_components.glinet_router.hub import GLinetHub

    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    assert hub.parallel_requests is False


def test_parallel_requests_property_explicit_true() -> None:
    from custom_components.glinet_router.const import CONF_PARALLEL_REQUESTS
    from custom_components.glinet_router.hub import GLinetHub

    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_PARALLEL_REQUESTS: True}
    assert hub.parallel_requests is True


def test_firmware_version_tuple_decodes_sw_version() -> None:
    from custom_components.glinet_router.hub import GLinetHub

    hub = GLinetHub.__new__(GLinetHub)
    hub._sw_version = "4.9.0"
    assert hub.firmware_version_tuple == (4, 9, 0, 0)

    hub._sw_version = "4.8.1-rc2"
    assert hub.firmware_version_tuple == (4, 8, 1, 2)

    hub._sw_version = "UNKNOWN"
    assert hub.firmware_version_tuple is None

    hub._sw_version = ""
    assert hub.firmware_version_tuple is None


def test_is_firmware_4_9_or_above_uses_sw_version() -> None:
    from custom_components.glinet_router.hub import GLinetHub

    hub = GLinetHub.__new__(GLinetHub)
    hub._api = None

    hub._sw_version = "4.9.0"
    assert hub.is_firmware_4_9_or_above is True

    hub._sw_version = "4.9.1"
    assert hub.is_firmware_4_9_or_above is True

    hub._sw_version = "4.8.3"
    assert hub.is_firmware_4_9_or_above is False

    hub._sw_version = "4.8.0"
    assert hub.is_firmware_4_9_or_above is False

    hub._sw_version = "UNKNOWN"
    hub._api = types.SimpleNamespace(_firmware_version=(4, 9, 0, 0))
    assert hub.is_firmware_4_9_or_above is True

    hub._api = types.SimpleNamespace(_firmware_version=(4, 8, 0, 0))
    assert hub.is_firmware_4_9_or_above is False

    hub._api = types.SimpleNamespace(_firmware_version=None)
    assert hub.is_firmware_4_9_or_above is False


async def test_fetch_all_data_with_no_optional_features_still_runs_core_fetches(
    monkeypatch,
) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: []}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._host = "192.168.8.1"
    hub._last_upgrade_check = None
    hub.hass = object()

    called: list[str] = []

    async def fake_fetch_system_status() -> None:
        called.append("system")

    async def fake_fetch_kmwan_status() -> None:
        called.append("kmwan")

    async def fake_fetch_connected_devices() -> None:
        called.append("clients")

    async def fake_fetch_wifi_interfaces() -> None:
        called.append("wifi")

    async def fake_fetch_fan_status() -> None:
        called.append("fan")

    async def fake_fetch_led_status() -> None:
        called.append("led")

    hub.fetch_system_status = fake_fetch_system_status
    hub.fetch_kmwan_status = fake_fetch_kmwan_status
    hub.fetch_connected_devices = fake_fetch_connected_devices
    hub.fetch_wifi_interfaces = fake_fetch_wifi_interfaces
    hub.fetch_fan_status = fake_fetch_fan_status
    hub.fetch_led_status = fake_fetch_led_status
    hub.refresh_session_token = _noop

    hub.fetch_led_status = fake_fetch_led_status
    await hub.fetch_all_data()

    assert called == ["system", "kmwan", "clients", "wifi", "fan", "led"]
    assert hub._wireguard_clients == {}
    assert hub._wireguard_connections is None
    assert hub._tailscale_config == {}
    assert hub._tailscale_connection is None
    assert hub._cellular_status == {}
    assert hub._modems == {}
    assert hub._repeater_status is None
    assert hub._repeater_config == {}
    assert hub._saved_networks == []


async def test_fetch_all_data_includes_wireguard_when_enabled(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: [FEATURE_WG_CLIENT, FEATURE_WG_SERVER]}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._host = "192.168.8.1"
    hub._last_upgrade_check = None
    hub.hass = object()

    called: list[str] = []

    async def fake_fetch_system_status() -> None:
        called.append("system")

    async def fake_fetch_kmwan_status() -> None:
        called.append("kmwan")

    async def fake_fetch_connected_devices() -> None:
        called.append("clients")

    async def fake_fetch_wifi_interfaces() -> None:
        called.append("wifi")

    async def fake_fetch_wireguard_clients() -> None:
        called.append("wg_client")

    async def fake_fetch_wg_server_status() -> None:
        called.append("wg_server")

    async def fake_fetch_fan_status() -> None:
        called.append("fan")

    async def fake_fetch_led_status() -> None:
        called.append("led")

    hub.fetch_system_status = fake_fetch_system_status
    hub.fetch_kmwan_status = fake_fetch_kmwan_status
    hub.fetch_connected_devices = fake_fetch_connected_devices
    hub.fetch_wifi_interfaces = fake_fetch_wifi_interfaces
    hub.fetch_wireguard_clients = fake_fetch_wireguard_clients
    hub.fetch_wg_server_status = fake_fetch_wg_server_status
    hub.fetch_fan_status = fake_fetch_fan_status
    hub.refresh_session_token = _noop

    hub.fetch_led_status = fake_fetch_led_status
    await hub.fetch_all_data()

    assert "wg_client" in called
    assert "wg_server" in called


async def test_fetch_all_data_skips_upgrade_info_within_a_day(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: []}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._host = "192.168.8.1"
    hub.hass = object()
    hub._last_upgrade_check = utcnow() - timedelta(hours=12)

    called: list[str] = []

    async def fake_fetch_system_status() -> None:
        called.append("system")

    async def fake_fetch_kmwan_status() -> None:
        called.append("kmwan")

    async def fake_fetch_connected_devices() -> None:
        called.append("clients")

    async def fake_fetch_wifi_interfaces() -> None:
        called.append("wifi")

    async def fake_fetch_fan_status() -> None:
        called.append("fan")

    async def fake_fetch_led_status() -> None:
        called.append("led")

    async def fake_fetch_upgrade_info() -> None:
        called.append("upgrade")

    hub.fetch_system_status = fake_fetch_system_status
    hub.fetch_kmwan_status = fake_fetch_kmwan_status
    hub.fetch_connected_devices = fake_fetch_connected_devices
    hub.fetch_wifi_interfaces = fake_fetch_wifi_interfaces
    hub.fetch_fan_status = fake_fetch_fan_status
    hub.fetch_led_status = fake_fetch_led_status
    hub.fetch_upgrade_info = fake_fetch_upgrade_info
    hub.refresh_session_token = _noop

    await hub.fetch_all_data()

    assert "upgrade" not in called
    assert called == ["system", "kmwan", "clients", "wifi", "fan", "led"]


async def test_fetch_all_data_runs_upgrade_info_after_a_day(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: []}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._host = "192.168.8.1"
    hub.hass = object()
    hub._last_upgrade_check = utcnow() - timedelta(days=2)

    called: list[str] = []

    async def fake_fetch_system_status() -> None:
        called.append("system")

    async def fake_fetch_kmwan_status() -> None:
        called.append("kmwan")

    async def fake_fetch_connected_devices() -> None:
        called.append("clients")

    async def fake_fetch_wifi_interfaces() -> None:
        called.append("wifi")

    async def fake_fetch_fan_status() -> None:
        called.append("fan")

    async def fake_fetch_led_status() -> None:
        called.append("led")

    async def fake_fetch_upgrade_info() -> None:
        called.append("upgrade")

    hub.fetch_system_status = fake_fetch_system_status
    hub.fetch_kmwan_status = fake_fetch_kmwan_status
    hub.fetch_connected_devices = fake_fetch_connected_devices
    hub.fetch_wifi_interfaces = fake_fetch_wifi_interfaces
    hub.fetch_fan_status = fake_fetch_fan_status
    hub.fetch_led_status = fake_fetch_led_status
    hub.fetch_upgrade_info = fake_fetch_upgrade_info
    hub.refresh_session_token = _noop

    await hub.fetch_all_data()

    assert "upgrade" in called
    assert called[0:6] == ["system", "kmwan", "upgrade", "clients", "wifi", "fan"]


async def test_scan_wifi_networks_stores_results(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._api = types.SimpleNamespace()
    hub._invoke_api = lambda api_callable: api_callable()
    hub._settings = {}
    hub._factory_mac = "00:00:00:00:00:00"
    hub.hass = object()
    hub._scanned_networks = []
    hub._last_wifi_scan = None

    async def fake_scan_wifi_networks(params: dict[str, Any]) -> list[dict[str, Any]]:
        calls.append(params)
        return [
            {
                "ssid": "TestNet",
                "bssid": "aa:bb:cc:dd:ee:ff",
                "signal": -50,
                "band": "5g",
                "encryption": {"enabled": False, "description": "Open"},
                "saved": False,
                "channel": 36,
            }
        ]

    hub._api.repeater = types.SimpleNamespace(scan=fake_scan_wifi_networks)

    calls: list[Any] = []

    def fake_dispatcher_send(hass: Any, event: str) -> None:
        calls.append(event)

    import custom_components.glinet_router.hub as hub_module

    monkeypatch.setattr(hub_module, "async_dispatcher_send", fake_dispatcher_send)

    networks = await hub.scan_wifi_networks(all_band=True, dfs=True, refresh=True)

    assert len(networks) == 1
    assert networks[0].ssid == "TestNet"
    assert hub._scanned_networks[0].ssid == "TestNet"
    assert hub._last_wifi_scan is not None
    assert calls == [
        {"refresh": True},
        "glinet_router-networks-update-00:00:00:00:00:00",
    ]


async def test_connect_to_wifi_calls_router_api_and_refreshes_status(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    called: list[Any] = []

    class RepeaterModule:
        async def connect(
            self,
            params: dict[str, Any],
        ) -> dict[str, Any]:
            called.append(params)
            return {}

    class RouterApi:
        repeater = RepeaterModule()

    async def fake_fetch_repeater_status() -> None:
        called.append("fetch_status")

    hub._api = RouterApi()
    hub._invoke_api = lambda api_callable: api_callable()
    hub.fetch_repeater_status = fake_fetch_repeater_status

    await hub.connect_to_wifi("test-ssid", "pass", remember=False, bssid="aa:bb")

    assert called == [
        {
            "ssid": "test-ssid",
            "remember": False,
            "manual": False,
            "protocol": "dhcp",
            "disguise": False,
            "auto_portal": False,
            "key": "pass",
            "bssid": "aa:bb",
        },
        "fetch_status",
    ]


async def test_connect_to_open_wifi_omits_empty_optional_fields(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    called: list[Any] = []

    class RepeaterModule:
        async def connect(
            self,
            params: dict[str, Any],
        ) -> dict[str, Any]:
            called.append(params)
            return {}

    class RouterApi:
        repeater = RepeaterModule()

    async def fake_fetch_repeater_status() -> None:
        called.append("fetch_status")

    hub._api = RouterApi()
    hub._invoke_api = lambda api_callable: api_callable()
    hub.fetch_repeater_status = fake_fetch_repeater_status

    await hub.connect_to_wifi("open-ssid", "")

    assert called == [
        {
            "ssid": "open-ssid",
            "remember": True,
            "manual": False,
            "protocol": "dhcp",
            "disguise": False,
            "auto_portal": False,
        },
        "fetch_status",
    ]


async def test_disconnect_wifi_calls_router_api_and_refreshes_status(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    called: list[str] = []

    class RepeaterModule:
        async def disconnect(self) -> dict[str, Any]:
            called.append("disconnect")
            return {}

    class RouterApi:
        repeater = RepeaterModule()

    async def fake_fetch_repeater_status() -> None:
        called.append("fetch_status")

    hub._api = RouterApi()
    hub._invoke_api = lambda api_callable: api_callable()
    hub.fetch_repeater_status = fake_fetch_repeater_status

    await hub.disconnect_wifi()

    assert called == ["disconnect", "fetch_status"]


async def test_set_repeater_band_updates_config(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    called: list[Any] = []

    class RepeaterModule:
        async def set_config(self, params: dict[str, Any]) -> dict[str, Any]:
            called.append(params.get("lock_band"))
            return {}

    class RouterApi:
        repeater = RepeaterModule()

    async def fake_fetch_repeater_config() -> None:
        called.append("fetch_config")

    hub._api = RouterApi()
    hub._invoke_api = lambda api_callable: api_callable()
    hub.fetch_repeater_config = fake_fetch_repeater_config

    await hub.set_repeater_band("5g")

    assert called == ["5g", "fetch_config"]


async def test_set_repeater_smart_reconnect_updates_config() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    called: list[Any] = []

    class RepeaterModule:
        async def set_config(self, params: dict[str, Any]) -> dict[str, Any]:
            called.append(params)
            return {}

    async def fake_fetch_repeater_config() -> None:
        called.append("fetch_config")

    hub._api = SimpleNamespace(repeater=RepeaterModule())
    hub._invoke_api = lambda api_callable: api_callable()
    hub.fetch_repeater_config = fake_fetch_repeater_config

    await hub.set_repeater_smart_reconnect(True)

    assert called == [{"smart_reconnect": True}, "fetch_config"]


async def test_set_repeater_bare_mode_calls_expected_methods() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    called: list[str] = []

    class RepeaterModule:
        async def enter_bare_mode(self) -> dict[str, Any]:
            called.append("enter")
            return {}

        async def exit_bare_mode(self) -> dict[str, Any]:
            called.append("exit")
            return {}

    async def fake_fetch_repeater_status() -> None:
        called.append("fetch_status")

    hub._api = SimpleNamespace(repeater=RepeaterModule())
    hub._invoke_api = lambda api_callable: api_callable()
    hub.fetch_repeater_status = fake_fetch_repeater_status

    await hub.set_repeater_bare_mode(True)
    await hub.set_repeater_bare_mode(False)

    assert called == ["enter", "fetch_status", "exit", "fetch_status"]


async def test_fetch_repeater_status_returns_none_when_unavailable() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._invoke_optional_api = AsyncMock(return_value=None)
    hub._settings = {}
    hub._api = SimpleNamespace(repeater=SimpleNamespace(get_status=object()))
    hub._repeater_status = RepeaterStatus(RepeaterState.CONNECTED)

    await hub.fetch_repeater_status()

    assert hub._repeater_status is None


async def test_fetch_repeater_config_stores_response() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._invoke_optional_api = AsyncMock(return_value={"lock_band": "2g"})
    hub._settings = {}
    hub._api = SimpleNamespace(repeater=SimpleNamespace(get_config=object()))

    await hub.fetch_repeater_config()

    assert hub._repeater_config == {"lock_band": "2g"}


async def test_get_saved_wifi_networks_and_remove_saved_wifi_network(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    api_calls: list[str] = []

    class RepeaterModule:
        async def get_saved_ap_list(self) -> list[dict[str, Any]]:
            api_calls.append("get_saved")
            return [{"ssid": "TestNet", "bssid": "aa:bb"}]

        async def remove_saved_ap(self, ssid: str) -> dict[str, Any]:
            api_calls.append(f"remove:{ssid}")
            return {}

    class RouterApi:
        repeater = RepeaterModule()

    async def invoke_api(callable: Any) -> Any:
        return await callable()

    hub._api = RouterApi()
    hub._invoke_api = invoke_api

    saved = await hub.get_saved_wifi_networks()
    await hub.remove_saved_wifi_network("TestNet")

    assert saved == [{"ssid": "TestNet", "bssid": "aa:bb"}]
    assert api_calls == ["get_saved", "remove:TestNet", "get_saved"]


async def test_async_initialize_hub_cleans_up_orphaned_entities(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: []}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"

    orphan_entry = types.SimpleNamespace(
        entity_id="sensor.glinet_cellular_signal",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_signal",
        domain="sensor",
    )
    valid_entry = types.SimpleNamespace(
        entity_id="sensor.glinet_uptime",
        unique_id="glinet_sensor/00:11:22:33:44:55/system_uptime",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(return_value=[orphan_entry, valid_entry]),
    )

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    mock_er.async_remove.assert_called_once_with("sensor.glinet_cellular_signal")


async def test_async_initialize_hub_removes_legacy_cellular_sensors_on_firmware_4_9(
    monkeypatch,
) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: ["cellular"]}
    hub._entry = types.SimpleNamespace(
        entry_id="test_entry",
        async_on_unload=lambda fn: None,
    )
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"
    hub._sw_version = "4.9.0"
    hub._api = None

    legacy_signal = types.SimpleNamespace(
        entity_id="sensor.glinet_cellular_signal",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_signal",
        domain="sensor",
    )
    legacy_rssi = types.SimpleNamespace(
        entity_id="sensor.glinet_cellular_rssi",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_rssi",
        domain="sensor",
    )
    kept_ipv4 = types.SimpleNamespace(
        entity_id="sensor.cellular_wan_ipv4",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_ipv4",
        domain="sensor",
    )
    kept_rsrp = types.SimpleNamespace(
        entity_id="sensor.glinet_cellular_rsrp",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_rsrp",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(
            return_value=[
                legacy_signal,
                legacy_rssi,
                kept_ipv4,
                kept_rsrp,
            ]
        ),
    )

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    assert mock_er.async_remove.call_count == 2
    mock_er.async_remove.assert_any_call("sensor.glinet_cellular_signal")
    mock_er.async_remove.assert_any_call("sensor.glinet_cellular_rssi")
    for call in mock_er.async_remove.call_args_list:
        assert call.args[0] != "sensor.cellular_wan_ipv4"
        assert call.args[0] != "sensor.glinet_cellular_rsrp"


async def test_async_initialize_hub_keeps_legacy_cellular_sensors_on_firmware_4_8(
    monkeypatch,
) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: ["cellular"]}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"
    hub._sw_version = "4.8.3"
    hub._api = None

    legacy_signal = types.SimpleNamespace(
        entity_id="sensor.glinet_cellular_signal",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_signal",
        domain="sensor",
    )
    legacy_rssi = types.SimpleNamespace(
        entity_id="sensor.glinet_cellular_rssi",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_rssi",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(return_value=[legacy_signal, legacy_rssi]),
    )

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    assert mock_er.async_remove.call_count == 0


async def test_async_initialize_hub_cleans_up_repeater_entities_when_disabled(
    monkeypatch,
) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: []}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"

    repeater_entries = [
        types.SimpleNamespace(
            entity_id="sensor.repeater_state",
            unique_id="glinet_sensor/00:11:22:33:44:55/repeater_state",
            domain="sensor",
        ),
        types.SimpleNamespace(
            entity_id="binary_sensor.repeater_connected",
            unique_id="glinet_binary_sensor/00:11:22:33:44:55/repeater_connected",
            domain="binary_sensor",
        ),
        types.SimpleNamespace(
            entity_id="select.wifi_network",
            unique_id="glinet_select/00:11:22:33:44:55/wifi_network",
            domain="select",
        ),
        types.SimpleNamespace(
            entity_id="select.repeater_band",
            unique_id="glinet_select/00:11:22:33:44:55/repeater_band",
            domain="select",
        ),
        types.SimpleNamespace(
            entity_id="switch.repeater_auto_switch",
            unique_id="glinet_switch/00:11:22:33:44:55/repeater_auto_switch",
            domain="switch",
        ),
        types.SimpleNamespace(
            entity_id="button.scan_wifi",
            unique_id="glinet_button/00:11:22:33:44:55/scan_wifi",
            domain="button",
        ),
        types.SimpleNamespace(
            entity_id="button.disconnect_repeater",
            unique_id="glinet_button/00:11:22:33:44:55/disconnect_repeater",
            domain="button",
        ),
    ]
    valid_entry = types.SimpleNamespace(
        entity_id="sensor.glinet_uptime",
        unique_id="glinet_sensor/00:11:22:33:44:55/system_uptime",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(return_value=[*repeater_entries, valid_entry]),
    )

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    assert mock_er.async_remove.call_count == len(repeater_entries)
    for entry in repeater_entries:
        mock_er.async_remove.assert_any_call(entry.entity_id)


async def test_async_initialize_hub_cleans_up_unselected_wan_status_sensors(
    monkeypatch,
) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {
        CONF_ADD_ALL_DEVICES: True,
        CONF_WAN_STATUS_MONITORS: ["wan:ipv4", "wan:ipv6", "wwan:ipv4"],
    }
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"

    selected_wan = types.SimpleNamespace(
        entity_id="sensor.ethernet_1_status",
        unique_id="glinet_sensor/00:11:22:33:44:55/wan_status_wan",
        domain="sensor",
    )
    selected_legacy_wwan = types.SimpleNamespace(
        entity_id="sensor.repeater_ipv4_status",
        unique_id="glinet_sensor/00:11:22:33:44:55/wan_status_wwan_ipv4",
        domain="sensor",
    )
    unselected_secondwan = types.SimpleNamespace(
        entity_id="sensor.ethernet_2_status",
        unique_id="glinet_sensor/00:11:22:33:44:55/wan_status_secondwan",
        domain="sensor",
    )
    unselected_legacy_wwan = types.SimpleNamespace(
        entity_id="sensor.repeater_ipv6_status",
        unique_id="glinet_sensor/00:11:22:33:44:55/wan_status_wwan_ipv6",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(
            return_value=[
                selected_wan,
                selected_legacy_wwan,
                unselected_secondwan,
                unselected_legacy_wwan,
            ]
        ),
    )

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    assert mock_er.async_remove.call_count == 2
    mock_er.async_remove.assert_any_call("sensor.ethernet_2_status")
    mock_er.async_remove.assert_any_call("sensor.repeater_ipv6_status")


async def test_async_initialize_hub_cleans_up_unselected_cellular_ip_sensors(
    monkeypatch,
) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {
        CONF_ADD_ALL_DEVICES: True,
        CONF_WAN_STATUS_MONITORS: ["wan:ipv4", "modem_0001:ipv4"],
        CONF_ENABLED_FEATURES: ["cellular"],
    }
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"

    selected_ipv4 = types.SimpleNamespace(
        entity_id="sensor.cellular_wan_ipv4",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_ipv4",
        domain="sensor",
    )
    unselected_ipv6 = types.SimpleNamespace(
        entity_id="sensor.cellular_wan_ipv6",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_ipv6",
        domain="sensor",
    )
    unrelated = types.SimpleNamespace(
        entity_id="sensor.connected_clients",
        unique_id="glinet_sensor/00:11:22:33:44:55/connected_clients",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(
            return_value=[
                selected_ipv4,
                unselected_ipv6,
                unrelated,
            ]
        ),
    )

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    assert mock_er.async_remove.call_count == 1
    mock_er.async_remove.assert_any_call("sensor.cellular_wan_ipv6")


async def test_async_cleanup_cellular_limit_sensors_removes_disabled(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._factory_mac = "00:11:22:33:44:55"
    hub._entity_cleanup_rules = []
    hub._traffic_sim_data = {
        1: {"slot": 1, "sim_type": 0, "limit_enabled": True, "traffic_total": 100},
        2: {"slot": 2, "sim_type": 0, "limit_enabled": False, "traffic_total": 50},
    }
    hub.hass = MagicMock()

    sim1_data_limit = types.SimpleNamespace(
        entity_id="sensor.cellular_sim_1_data_limit",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_1_0_data_limit",
        domain="sensor",
    )
    sim1_days_until_reset = types.SimpleNamespace(
        entity_id="sensor.cellular_sim_1_days_until_reset",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_1_0_days_until_reset",
        domain="sensor",
    )
    sim1_traffic_total = types.SimpleNamespace(
        entity_id="sensor.cellular_sim_1_traffic_total",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_1_0_traffic_total",
        domain="sensor",
    )
    sim2_data_limit = types.SimpleNamespace(
        entity_id="sensor.cellular_sim_2_data_limit",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_2_0_data_limit",
        domain="sensor",
    )
    sim2_days_until_reset = types.SimpleNamespace(
        entity_id="sensor.cellular_sim_2_days_until_reset",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_2_0_days_until_reset",
        domain="sensor",
    )
    sim2_traffic_total = types.SimpleNamespace(
        entity_id="sensor.cellular_sim_2_traffic_total",
        unique_id="glinet_sensor/00:11:22:33:44:55/cellular_traffic_sim_2_0_traffic_total",
        domain="sensor",
    )
    unrelated = types.SimpleNamespace(
        entity_id="sensor.connected_clients",
        unique_id="glinet_sensor/00:11:22:33:44:55/connected_clients",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(
            return_value=[
                sim1_data_limit,
                sim1_days_until_reset,
                sim1_traffic_total,
                sim2_data_limit,
                sim2_days_until_reset,
                sim2_traffic_total,
                unrelated,
            ]
        ),
    )

    hub._refresh_cellular_limit_cleanup_rule()
    await hub._async_cleanup_orphaned_sensor_entities()

    removed = {call.args[0] for call in mock_er.async_remove.call_args_list}
    assert "sensor.cellular_sim_2_data_limit" in removed
    assert "sensor.cellular_sim_2_days_until_reset" in removed
    assert "sensor.cellular_sim_1_data_limit" not in removed
    assert "sensor.cellular_sim_1_days_until_reset" not in removed
    assert "sensor.cellular_sim_1_traffic_total" not in removed
    assert "sensor.cellular_sim_2_traffic_total" not in removed
    assert "sensor.connected_clients" not in removed


async def test_fetch_traffic_config_dispatches_event_when_sim_data_updates(
    monkeypatch,
) -> None:
    import custom_components.glinet_router.hub as hub_module

    dispatched: list[str] = []
    monkeypatch.setattr(
        hub_module,
        "async_dispatcher_send",
        lambda hass, signal: dispatched.append(signal),
    )

    hub = GLinetHub.__new__(GLinetHub)
    hub._modems = {"1-1:00.0": {"bus": "0001:01:00.0"}}
    hub._default_modem_bus = "0001:01:00.0"
    hub.hass = MagicMock()
    hub._factory_mac = "AA:BB:CC:DD:EE:FF"
    hub._traffic_sim_data = {}
    hub._traffic_config_save_to_flash = None
    hub._entity_cleanup_rules = []
    hub._sw_version = "4.8.0"
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    mock_api = MagicMock()
    mock_api.modem.get_traffic_config = AsyncMock(
        return_value={
            "save_to_flash": True,
            "sim1_traffic_total": "100",
            "sim1_limit": {
                "enable": True,
                "threshold": "1000",
                "unit": "MB",
                "reset_period": "month",
                "day": "1",
                "hour": "0",
                "month": "0",
            },
            "sim2_traffic_total": "0",
            "sim2_limit": {"enable": False},
        }
    )
    hub._api = mock_api
    hub._invoke_optional_api = lambda fn: fn()

    await hub.fetch_traffic_config()

    assert hub.event_cellular_traffic_config_updated in dispatched


def test_event_cellular_traffic_config_updated_is_per_mac() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._factory_mac = "AA:BB:CC:DD:EE:FF"
    assert (
        hub.event_cellular_traffic_config_updated
        == "glinet_router-cellular-traffic-config-updated-AA:BB:CC:DD:EE:FF"
    )


async def test_register_periodic_cleanup_registers_interval_tracker(monkeypatch) -> None:
    import custom_components.glinet_router.hub as hub_module

    captured: dict = {}

    def _fake_track_time_interval(hass, action, interval):
        captured["hass"] = hass
        captured["action"] = action
        captured["interval"] = interval
        return lambda: None

    monkeypatch.setattr(hub_module, "async_track_time_interval", _fake_track_time_interval)

    hub = GLinetHub.__new__(GLinetHub)
    hub.hass = MagicMock()
    on_unload_calls: list = []
    hub._entry = types.SimpleNamespace(
        entry_id="test_entry",
        async_on_unload=lambda fn: on_unload_calls.append(fn),
    )

    hub._register_periodic_cleanup()

    assert on_unload_calls
    assert captured["action"] == hub._periodic_cleanup_callback
    assert captured["interval"] == timedelta(minutes=30)


async def test_periodic_cleanup_callback_swallows_transport_errors(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)

    async def _boom() -> None:
        raise TimeoutError("router unreachable")

    hub._async_cleanup_orphaned_sensor_entities = _boom

    await hub._periodic_cleanup_callback(datetime.now())


async def test_async_cleanup_orphaned_sensor_entities_runs_with_no_rules() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub._factory_mac = "00:11:22:33:44:55"
    hub._traffic_sim_data = {}
    hub._entity_cleanup_rules = []
    hub._entity_cleanup_rules = []
    hub.hass = MagicMock()

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()
    import homeassistant.helpers.entity_registry as er

    monkeypatch_holder = {}

    def _fake_async_get(hass):
        return mock_er

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch_holder["er"] = er
    # Call without monkeypatching — the rule list is empty so nothing should be removed
    await hub._async_cleanup_orphaned_sensor_entities()


async def test_fetch_connected_devices_respects_add_all_devices_option(monkeypatch) -> None:
    import custom_components.glinet_router.hub as hub_module

    monkeypatch.setattr(hub_module, "async_dispatcher_send", _noop_arg)

    hub = GLinetHub.__new__(GLinetHub)
    hub._options = {"consider_home": 0}
    hub._settings = {CONF_ADD_ALL_DEVICES: True}
    hub._factory_mac = "00:00:00:00:00:00"
    hub._devices = {}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", unique_id="unique_id")
    hub.hass = MagicMock()

    mock_dr = MagicMock()
    mock_dr.async_get_device_by_connection.return_value = None
    import homeassistant.helpers.device_registry as dr

    monkeypatch.setattr(dr, "async_get", lambda _: mock_dr)

    hub._api = types.SimpleNamespace(clients=types.SimpleNamespace(get_online=AsyncMock()))
    hub._invoke_api = AsyncMock(
        return_value={"11:22:33:44:55:66": {"online": True, "ip": "1.1.1.1"}}
    )

    await hub.fetch_connected_devices()

    assert "11:22:33:44:55:66" in hub._devices
    assert hub._devices["11:22:33:44:55:66"].is_known is False


async def test_async_initialize_hub_cleans_up_unknown_devices(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ADD_ALL_DEVICES: False}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"

    unknown_tracker = types.SimpleNamespace(
        entity_id="device_tracker.unknown", unique_id="aa:bb:cc:dd:ee:ff", domain="device_tracker"
    )
    unknown_sensor = types.SimpleNamespace(
        entity_id="sensor.unknown_bandwidth",
        unique_id="glinet_client_sensor/aa:bb:cc:dd:ee:ff/download",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.device_registry as dr
    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(return_value=[unknown_tracker, unknown_sensor]),
    )

    # Device does NOT exist in HA — orphan entities should be cleaned up
    mock_dr = MagicMock()
    mock_dr.async_get_device_by_connection.return_value = None
    monkeypatch.setattr(dr, "async_get", lambda _: mock_dr)

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    assert mock_er.async_remove.call_count == 2
    mock_er.async_remove.assert_any_call("device_tracker.unknown")
    mock_er.async_remove.assert_any_call("sensor.unknown_bandwidth")

    # Device never existed, so nothing to remove from the registry
    mock_dr.async_remove_device.assert_not_called()


async def test_async_initialize_hub_keeps_known_devices(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ADD_ALL_DEVICES: False}
    hub._entry = types.SimpleNamespace(entry_id="test_entry", async_on_unload=lambda fn: None)
    hub.hass = MagicMock()
    hub._late_init_complete = True
    hub._factory_mac = "00:11:22:33:44:55"

    known_tracker = types.SimpleNamespace(
        entity_id="device_tracker.known", unique_id="aa:bb:cc:dd:ee:ff", domain="device_tracker"
    )
    known_sensor = types.SimpleNamespace(
        entity_id="sensor.known_bandwidth",
        unique_id="glinet_client_sensor/aa:bb:cc:dd:ee:ff/download",
        domain="sensor",
    )

    mock_er = MagicMock()
    mock_er.async_remove = MagicMock()

    import homeassistant.helpers.device_registry as dr
    import homeassistant.helpers.entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda _: mock_er)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        MagicMock(return_value=[known_tracker, known_sensor]),
    )

    # Device already exists in HA — should be preserved even with discovery off
    mock_dr = MagicMock()
    mock_dr.async_get_device_by_connection.return_value = types.SimpleNamespace(
        id="device_id", name="Known Device"
    )
    monkeypatch.setattr(dr, "async_get", lambda _: mock_dr)

    hub.refresh_session_token = _noop
    hub.fetch_all_data = _noop

    await hub.async_initialize_hub()

    # No entity or device should be removed
    mock_er.async_remove.assert_not_called()
    mock_dr.async_remove_device.assert_not_called()


async def test_fetch_wg_server_status(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}

    class WgServerModule:
        async def get_status(self) -> dict[str, Any]:
            return {"server": {"status": 1}, "peers": [{"status": 1}, {"status": 0}]}

    hub._api = types.SimpleNamespace(wg_server=WgServerModule())
    hub._invoke_api = lambda api_callable: api_callable()

    await hub.fetch_wg_server_status()

    assert hub.wg_server_status.enabled is True
    assert hub.wg_server_connected_users == 1


async def test_start_wg_server(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    called = []

    class WgServerModule:
        async def start(self) -> dict[str, Any]:
            called.append("start")
            return {"ok": True}

        async def get_status(self) -> dict[str, Any]:
            return {"server": {"status": 1}}

    hub._api = types.SimpleNamespace(wg_server=WgServerModule())
    hub._invoke_api = lambda api_callable: api_callable()

    await hub.start_wg_server()
    assert "start" in called


async def test_stop_wg_server(monkeypatch) -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {}
    called = []

    class WgServerModule:
        async def stop(self) -> dict[str, Any]:
            called.append("stop")
            return {"ok": True}

        async def get_status(self) -> dict[str, Any]:
            return {"server": {"status": 0}}

    hub._api = types.SimpleNamespace(wg_server=WgServerModule())
    hub._invoke_api = lambda api_callable: api_callable()

    await hub.stop_wg_server()
    assert "stop" in called


async def test_cleanup_stale_devices_removes_known_device_entities(monkeypatch) -> None:
    import custom_components.glinet_router.hub as hub_module

    hub = GLinetHub.__new__(GLinetHub)
    mac = "aa:bb:cc:dd:ee:ff"
    device = ClientDeviceInfo(mac)
    device.apply_update({"online": False})
    device._last_activity = hub_module.utcnow() - hub_module.timedelta(minutes=10)
    device.is_known = True
    hub._devices = {mac: device}
    hub._settings = {CONF_CLEANUP_DEVICES: 5}
    hub._entry = SimpleNamespace(entry_id="entry")
    hub.hass = object()

    tracker = SimpleNamespace(entity_id="device_tracker.phone", unique_id=mac)
    entity_registry = MagicMock()
    device_registry = MagicMock()
    device_registry.async_get_device_by_connection.return_value = SimpleNamespace(
        id="device-id",
    )

    monkeypatch.setattr(hub_module.er, "async_get", lambda _: entity_registry)
    monkeypatch.setattr(
        hub_module.er,
        "async_entries_for_config_entry",
        lambda *_: [tracker],
    )
    monkeypatch.setattr(hub_module.dr, "async_get", lambda _: device_registry)

    await hub._async_cleanup_stale_devices()

    assert hub._devices == {}
    entity_registry.async_remove.assert_called_once_with("device_tracker.phone")
    device_registry.async_remove_device.assert_called_once_with("device-id")


async def _noop() -> None:
    return None


def _noop_arg(*args, **kwargs) -> None:
    return None


def _make_entry(data: dict[str, Any] | None = None, options: dict[str, Any] | None = None):
    entry = SimpleNamespace()
    entry.data = data or {"host": "http://192.168.8.1", "password": "pass"}
    entry.options = options or {}
    entry.entry_id = "test_entry"
    entry.unique_id = "aa:bb:cc:dd:ee:ff"
    return entry


def test_hub_uses_configured_scan_interval() -> None:
    from datetime import timedelta

    entry = _make_entry(
        data={
            "host": "http://192.168.8.1",
            "password": "pass",
            CONF_SCAN_INTERVAL: 60,
        }
    )
    hub = GLinetHub(MagicMock(), entry)
    assert hub.update_interval == timedelta(seconds=60)


def test_hub_defaults_scan_interval_when_not_configured() -> None:
    from datetime import timedelta

    entry = _make_entry(
        data={
            "host": "http://192.168.8.1",
            "password": "pass",
        }
    )
    hub = GLinetHub(MagicMock(), entry)
    assert hub.update_interval == timedelta(seconds=30)


def test_hub_scan_interval_from_options_overrides_data() -> None:
    from datetime import timedelta

    entry = _make_entry(
        data={
            "host": "http://192.168.8.1",
            "password": "pass",
            CONF_SCAN_INTERVAL: 30,
        },
        options={CONF_SCAN_INTERVAL: 120},
    )
    hub = GLinetHub(MagicMock(), entry)
    assert hub.update_interval == timedelta(seconds=120)


def test_apply_option_updates_changes_scan_interval() -> None:
    from datetime import timedelta

    entry = _make_entry(
        data={
            "host": "http://192.168.8.1",
            "password": "pass",
            CONF_SCAN_INTERVAL: 30,
        }
    )
    hub = GLinetHub(MagicMock(), entry)
    assert hub.update_interval == timedelta(seconds=30)

    hub.apply_option_updates({CONF_SCAN_INTERVAL: 90})
    assert hub.update_interval == timedelta(seconds=90)


def test_apply_option_updates_without_scan_interval_keeps_default() -> None:
    from datetime import timedelta

    entry = _make_entry(
        data={
            "host": "http://192.168.8.1",
            "password": "pass",
        }
    )
    hub = GLinetHub(MagicMock(), entry)
    assert hub.update_interval == timedelta(seconds=30)

    hub.apply_option_updates({"some_other_option": "value"})
    assert hub.update_interval == timedelta(seconds=30)


def test_create_api_client_passes_verify_ssl_from_settings(monkeypatch) -> None:
    from custom_components.glinet_router.api.client import GLinetApiClient

    captured: dict[str, Any] = {}

    def fake_constructor(self, *args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(GLinetApiClient, "__init__", fake_constructor)

    entry = _make_entry(
        data={
            "host": "http://192.168.8.1",
            "password": "pass",
            CONF_VERIFY_SSL: False,
        }
    )
    hub = GLinetHub(MagicMock(), entry)

    hub._create_api_client()

    assert captured["verify_ssl"] is False
    assert captured["base_url"] == "http://192.168.8.1/rpc"


def test_create_api_client_defaults_verify_ssl_to_false(monkeypatch) -> None:
    from custom_components.glinet_router.api.client import GLinetApiClient

    captured: dict[str, Any] = {}

    def fake_constructor(self, *args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(GLinetApiClient, "__init__", fake_constructor)

    entry = _make_entry(data={"host": "http://192.168.8.1", "password": "pass"})
    hub = GLinetHub(MagicMock(), entry)

    hub._create_api_client()

    assert captured["verify_ssl"] is False
