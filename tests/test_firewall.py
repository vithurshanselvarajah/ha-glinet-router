from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.glinet_router.api.client import GLinetApiClient
from custom_components.glinet_router.const import (
    CONF_CLEANUP_DEVICES,
    CONF_ENABLED_FEATURES,
    FEATURE_FIREWALL,
)
from custom_components.glinet_router.entities.switch import GLinetDMZSwitch, GLinetWANAccessSwitch
from custom_components.glinet_router.hub import GLinetHub
from custom_components.glinet_router.models import ClientDeviceInfo
from tests.test_api_client import FakeSession


async def test_firewall_module_methods_use_expected_payloads() -> None:
    session = FakeSession(
        [
            {"result": {"res": [{"id": "rule-1"}]}},
            {"result": {"ok": True}},
            {"result": {"ok": True}},
            {"result": {"ok": True}},
            {"result": [{"name": "ACL"}]},
            {"result": {"ok": True}},
            {"result": {"ok": True}},
            {"result": {"ok": True}},
            {"result": {"zones": ["lan", "wan"]}},
            {"result": {"enabled": True, "dest_ip": "192.168.8.50"}},
            {"result": {"ok": True}},
            {"result": {"res": [{"id": "pf-1"}]}},
            {"result": {"ok": True}},
            {"result": {"ok": True}},
            {"result": {"ok": True}},
            {"result": {"enable_ping": True}},
            {"result": {"ok": True}},
            {"result": {"zones": ["lan", "wan"]}},
            {"result": []},
            {"result": []},
        ]
    )
    client = GLinetApiClient("http://router/rpc", session, sid="sid-1")

    assert await client.firewall.get_rule_list() == {"res": [{"id": "rule-1"}]}
    assert await client.firewall.add_rule({"name": "Allow SSH"}) == {"ok": True}
    assert await client.firewall.set_rule({"id": "rule-1", "name": "Allow SSH"}) == {"ok": True}
    assert await client.firewall.remove_rule({"id": "rule-1"}) == {"ok": True}
    assert await client.firewall.get_acl_rule_list() == [{"name": "ACL"}]
    assert await client.firewall.add_acl_rule({"name": "ACL"}) == {"ok": True}
    assert await client.firewall.edit_acl_rule({"id": "acl-1"}) == {"ok": True}
    assert await client.firewall.delete_acl_rule({"id": "acl-1"}) == {"ok": True}
    assert await client.firewall.get_acl_zone_list() == {"zones": ["lan", "wan"]}
    assert await client.firewall.get_dmz() == {
        "enabled": True,
        "dest_ip": "192.168.8.50",
    }
    assert await client.firewall.set_dmz(True, "192.168.8.50") == {"ok": True}
    assert await client.firewall.get_port_forward_list() == {"res": [{"id": "pf-1"}]}
    assert await client.firewall.add_port_forward({"name": "Web"}) == {"ok": True}
    assert await client.firewall.set_port_forward({"id": "pf-1"}) == {"ok": True}
    assert await client.firewall.remove_port_forward({"id": "pf-1"}) == {"ok": True}
    assert await client.firewall.get_wan_access() == {"enable_ping": True}
    assert await client.firewall.set_wan_access({"enable_ping": False}) == {"ok": True}
    assert await client.firewall.get_zone_list() == {"zones": ["lan", "wan"]}
    assert await client.firewall.order_acl_rule(["acl-1"]) == []
    assert await client.firewall.order_port_forward(["pf-1"]) == []

    assert [request["json"]["params"] for request in session.requests] == [
        ["sid-1", "firewall", "get_rule_list", {}],
        ["sid-1", "firewall", "add_rule", {"name": "Allow SSH"}],
        ["sid-1", "firewall", "set_rule", {"id": "rule-1", "name": "Allow SSH"}],
        ["sid-1", "firewall", "remove_rule", {"id": "rule-1"}],
        ["sid-1", "firewall", "get_acl_rule_list", {}],
        ["sid-1", "firewall", "add_acl_rule", {"name": "ACL"}],
        ["sid-1", "firewall", "edit_acl_rule", {"id": "acl-1"}],
        ["sid-1", "firewall", "delete_acl_rule", {"id": "acl-1"}],
        ["sid-1", "firewall", "get_acl_zone_list", {}],
        ["sid-1", "firewall", "get_dmz", {}],
        ["sid-1", "firewall", "set_dmz", {"enabled": True, "dest_ip": "192.168.8.50"}],
        ["sid-1", "firewall", "get_port_forward_list", {}],
        ["sid-1", "firewall", "add_port_forward", {"name": "Web"}],
        ["sid-1", "firewall", "set_port_forward", {"id": "pf-1"}],
        ["sid-1", "firewall", "remove_port_forward", {"id": "pf-1"}],
        ["sid-1", "firewall", "get_wan_access", {}],
        ["sid-1", "firewall", "set_wan_access", {"enable_ping": False}],
        ["sid-1", "firewall", "get_zone_list", {}],
        ["sid-1", "firewall", "order_acl_rule", {"id_list": ["acl-1"]}],
        ["sid-1", "firewall", "order_port_forward", {"id_list": ["pf-1"]}],
    ]


async def test_firewall_module_set_dmz_omits_empty_destination_ip() -> None:
    session = FakeSession([{"result": {"ok": True}}])
    client = GLinetApiClient("http://router/rpc", session, sid="sid-1")

    await client.firewall.set_dmz(False)

    assert session.requests[0]["json"]["params"] == [
        "sid-1",
        "firewall",
        "set_dmz",
        {"enabled": False},
    ]


async def test_hub_fetches_firewall_state() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._api = SimpleNamespace(
        firewall=SimpleNamespace(
            get_rule_list=object(),
            get_dmz=object(),
            get_port_forward_list=object(),
            get_wan_access=object(),
            get_zone_list=object(),
        )
    )
    responses = [
        {"res": [{"id": "rule-1"}]},
        {"enabled": True},
        {"res": [{"id": "pf-1"}]},
        {"enable_ping": True},
        {"zones": ["wan"]},
    ]
    hub._invoke_optional_api = AsyncMock(side_effect=responses)

    await hub.fetch_firewall_rules()
    await hub.fetch_dmz_config()
    await hub.fetch_port_forwards()
    await hub.fetch_wan_access()
    await hub.fetch_zone_list()

    assert hub._firewall_rules == [{"id": "rule-1"}]
    assert hub._dmz_config == {"enabled": True}
    assert hub._port_forwards == [{"id": "pf-1"}]
    assert hub._wan_access == {"enable_ping": True}
    assert hub._zone_list == {"zones": ["wan"]}


async def test_hub_firewall_mutations_call_api_and_refresh() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    api_calls: list[tuple[str, Any]] = []
    refreshes: list[str] = []

    class FirewallModule:
        async def add_rule(self, params: dict[str, Any]) -> None:
            api_calls.append(("add_rule", params))

        async def remove_rule(self, params: dict[str, Any]) -> None:
            api_calls.append(("remove_rule", params))

        async def add_port_forward(self, params: dict[str, Any]) -> None:
            api_calls.append(("add_port_forward", params))

        async def remove_port_forward(self, params: dict[str, Any]) -> None:
            api_calls.append(("remove_port_forward", params))

        async def set_dmz(self, enabled: bool, dest_ip: str | None = None) -> None:
            api_calls.append(("set_dmz", (enabled, dest_ip)))

        async def set_wan_access(self, config: dict[str, Any]) -> None:
            api_calls.append(("set_wan_access", config))

    async def invoke_api(api_callable: Any) -> Any:
        return await api_callable()

    async def fetch_firewall_rules() -> None:
        refreshes.append("firewall_rules")

    async def fetch_port_forwards() -> None:
        refreshes.append("port_forwards")

    async def fetch_dmz_config() -> None:
        refreshes.append("dmz")

    async def fetch_wan_access() -> None:
        refreshes.append("wan_access")

    hub._api = SimpleNamespace(firewall=FirewallModule())
    hub._invoke_api = invoke_api
    hub.fetch_firewall_rules = fetch_firewall_rules
    hub.fetch_port_forwards = fetch_port_forwards
    hub.fetch_dmz_config = fetch_dmz_config
    hub.fetch_wan_access = fetch_wan_access

    await hub.add_firewall_rule({"name": "Allow SSH"})
    await hub.remove_firewall_rule(rule_id="rule-1")
    await hub.add_port_forward({"name": "Web"})
    await hub.remove_port_forward(rule_id="pf-1")
    await hub.remove_port_forward(remove_all=True)
    await hub.set_dmz_config(True, "192.168.8.50")
    await hub.set_wan_access({"enable_ping": False})

    assert api_calls == [
        ("add_rule", {"name": "Allow SSH"}),
        ("remove_rule", {"id": "rule-1"}),
        ("add_port_forward", {"name": "Web"}),
        ("remove_port_forward", {"id": "pf-1"}),
        ("remove_port_forward", {"all": True}),
        ("set_dmz", (True, "192.168.8.50")),
        ("set_wan_access", {"enable_ping": False}),
    ]
    assert refreshes == [
        "firewall_rules",
        "firewall_rules",
        "port_forwards",
        "port_forwards",
        "port_forwards",
        "dmz",
        "wan_access",
    ]


async def test_hub_get_firewall_rule_summaries_returns_names_and_ids() -> None:
    hub = GLinetHub.__new__(GLinetHub)

    async def fetch_firewall_rules() -> None:
        hub._firewall_rules = [
            {"id": "rule-1", "name": "Allow SSH", "target": "ACCEPT"},
            {"id": "rule-2", "target": "DROP"},
        ]

    hub.fetch_firewall_rules = fetch_firewall_rules

    assert await hub.get_firewall_rule_summaries() == [
        {"id": "rule-1", "name": "Allow SSH"},
        {"id": "rule-2", "name": None},
    ]


async def test_fetch_all_data_includes_and_resets_firewall_state() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._settings = {CONF_ENABLED_FEATURES: [FEATURE_FIREWALL]}
    hub._entry = SimpleNamespace(entry_id="entry")
    hub._host = "192.168.8.1"
    hub.hass = object()
    called: list[str] = []

    async def record(name: str) -> None:
        called.append(name)

    hub.refresh_session_token = AsyncMock()
    hub.fetch_system_status = lambda: record("system")
    hub.fetch_kmwan_status = lambda: record("kmwan")
    hub.fetch_connected_devices = lambda: record("clients")
    hub.fetch_wifi_interfaces = lambda: record("wifi")
    hub.fetch_fan_status = lambda: record("fan")
    hub.fetch_led_status = lambda: record("led")
    hub.fetch_firewall_rules = lambda: record("firewall_rules")
    hub.fetch_dmz_config = lambda: record("dmz")
    hub.fetch_port_forwards = lambda: record("port_forwards")
    hub.fetch_wan_access = lambda: record("wan_access")
    hub.fetch_zone_list = lambda: record("zones")

    await hub.fetch_all_data()

    assert called == [
        "system",
        "kmwan",
        "clients",
        "wifi",
        "fan",
        "led",
        "firewall_rules",
        "dmz",
        "port_forwards",
        "wan_access",
        "zones",
    ]

    hub._settings = {CONF_ENABLED_FEATURES: []}
    hub._firewall_rules = [{"id": "rule-1"}]
    hub._dmz_config = {"enabled": True}
    hub._port_forwards = [{"id": "pf-1"}]
    hub._wan_access = {"enable_ping": True}
    hub._zone_list = {"zones": ["wan"]}
    called.clear()

    await hub.fetch_all_data()

    assert hub._firewall_rules == []
    assert hub._dmz_config == {}
    assert hub._port_forwards == []
    assert hub._wan_access == {}
    assert hub._zone_list == {}


async def test_fetch_system_status_stores_response() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._api = SimpleNamespace(system=SimpleNamespace(get_status=object()))
    hub._invoke_api = AsyncMock(return_value={"network": []})

    await hub.fetch_system_status()

    assert hub._system_status == {"network": []}


async def test_fetch_kmwan_status_stores_response() -> None:
    hub = GLinetHub.__new__(GLinetHub)
    hub._api = SimpleNamespace(system=SimpleNamespace(get_kmwan_status=object()))
    hub._invoke_optional_api = AsyncMock(
        return_value={"interfaces": [{"interface": "wan", "status_v4": 1, "status_v6": 1}]}
    )

    await hub.fetch_kmwan_status()

    assert hub.kmwan_status == {
        "interfaces": [{"interface": "wan", "status_v4": 1, "status_v6": 1}]
    }


async def test_cleanup_stale_devices_removes_unknown_device_entities(monkeypatch) -> None:
    import custom_components.glinet_router.hub as hub_module

    hub = GLinetHub.__new__(GLinetHub)
    mac = "aa:bb:cc:dd:ee:ff"
    device = ClientDeviceInfo(mac)
    device.apply_update({"online": False})
    device._last_activity = hub_module.utcnow() - hub_module.timedelta(minutes=10)
    device.is_known = False
    hub._devices = {mac: device}
    hub._settings = {CONF_CLEANUP_DEVICES: 5}
    hub._entry = SimpleNamespace(entry_id="entry")
    hub.hass = object()

    tracker = SimpleNamespace(entity_id="device_tracker.phone", unique_id=mac)
    sensor = SimpleNamespace(
        entity_id="sensor.phone_download",
        unique_id=f"glinet_client_sensor/{mac}/download",
    )
    retained = SimpleNamespace(entity_id="sensor.other", unique_id="other")
    entity_registry = MagicMock()
    device_registry = MagicMock()
    device_registry.async_get_device_by_connection.return_value = SimpleNamespace(
        id="device-id",
    )

    monkeypatch.setattr(hub_module.er, "async_get", lambda _: entity_registry)
    monkeypatch.setattr(
        hub_module.er,
        "async_entries_for_config_entry",
        lambda *_: [tracker, sensor, retained],
    )
    monkeypatch.setattr(hub_module.dr, "async_get", lambda _: device_registry)

    await hub._async_cleanup_stale_devices()

    assert hub._devices == {}
    entity_registry.async_remove.assert_any_call("device_tracker.phone")
    entity_registry.async_remove.assert_any_call("sensor.phone_download")
    assert entity_registry.async_remove.call_count == 2
    device_registry.async_remove_device.assert_called_once_with("device-id")


async def test_dmz_switch_exposes_state_and_disables_dmz() -> None:
    hub = SimpleNamespace(
        _dmz_config={"enabled": True, "dest_ip": "192.168.8.50"},
        device_mac="00:11:22:33:44:55",
        device_info={},
        hass=object(),
        set_dmz_config=AsyncMock(),
        async_request_refresh=AsyncMock(),
    )

    switch = GLinetDMZSwitch(hub)

    assert switch.unique_id == "glinet_switch/00:11:22:33:44:55/firewall_dmz"
    assert switch.name == "Firewall DMZ"
    assert switch.is_on is True
    assert switch.extra_state_attributes == {"destination_ip": "192.168.8.50"}

    await switch.async_turn_off()

    hub.set_dmz_config.assert_awaited_once_with(False)
    hub.async_request_refresh.assert_awaited_once()


async def test_wan_access_switch_toggles_selected_access_type() -> None:
    hub = SimpleNamespace(
        _wan_access={"enable_ping": False, "enable_ssh": True},
        device_mac="00:11:22:33:44:55",
        device_info={},
        hass=object(),
        set_wan_access=AsyncMock(),
        async_request_refresh=AsyncMock(),
    )

    switch = GLinetWANAccessSwitch(hub, "ping", "WAN Ping", "mdi:access-point-network")

    assert switch.unique_id == "glinet_switch/00:11:22:33:44:55/wan_access_ping"
    assert switch.name == "WAN Ping"
    assert switch.is_on is False

    await switch.async_turn_on()
    await switch.async_turn_off()

    hub.set_wan_access.assert_any_await({"enable_ping": True, "enable_ssh": True})
    hub.set_wan_access.assert_any_await({"enable_ping": False, "enable_ssh": True})
    assert hub.async_request_refresh.await_count == 2
