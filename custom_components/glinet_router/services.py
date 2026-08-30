from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.const import CONF_MAC
from homeassistant.core import SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ALL_BAND,
    ATTR_BLOCK,
    ATTR_BODY,
    ATTR_BSSID,
    ATTR_CAPACITY,
    ATTR_CAPACITY_ENABLED,
    ATTR_CONFIG,
    ATTR_CONTENT,
    ATTR_CUSTOM,
    ATTR_DEST,
    ATTR_DEST_IP,
    ATTR_DEST_PORT,
    ATTR_DFS,
    ATTR_DURATION,
    ATTR_ENABLED,
    ATTR_GROUP_ID,
    ATTR_INTERFACE,
    ATTR_LAN,
    ATTR_MAIN,
    ATTR_MESSAGE_ID,
    ATTR_METHOD,
    ATTR_MODE,
    ATTR_NAME,
    ATTR_PASSWORD,
    ATTR_PROTO,
    ATTR_RECIPIENT,
    ATTR_REFRESH,
    ATTR_REMEMBER,
    ATTR_REMOVE_ALL,
    ATTR_RULE_ID,
    ATTR_SCOPE,
    ATTR_SENSITIVITY,
    ATTR_SRC,
    ATTR_SRC_DPORT,
    ATTR_SRC_IP,
    ATTR_SRC_MAC,
    ATTR_SRC_PORT,
    ATTR_SSID,
    ATTR_TARGET,
    ATTR_TEMP_HIGH,
    ATTR_TEMP_HIGH_ENABLED,
    ATTR_TEMP_LOW,
    ATTR_TEMP_LOW_ENABLED,
    ATTR_TEMPERATURE,
    ATTR_TEXT,
    ATTR_VPN,
    ATTR_WIFI_2G,
    ATTR_WIFI_5G,
    ATTR_WIFI_PASSWORD,
    CONF_ENABLED_FEATURES,
    DOMAIN,
    FEATURE_FIREWALL,
    FEATURE_KMWAN,
    FEATURE_MCU_BATTERY,
    FEATURE_MCU_OLED,
    FEATURE_MWAN3,
    FEATURE_OPTIONS,
    FEATURE_PARENTAL_CONTROL,
    FEATURE_PLAYGROUND,
    FEATURE_REPEATER,
    FEATURE_SMS,
    SERVICE_ACCESS_CONTROL_SET_DEVICE_BLOCK,
    SERVICE_ACCESS_CONTROL_SET_MODE,
    SERVICE_ADD_FIREWALL_RULE,
    SERVICE_ADD_PORT_FORWARD,
    SERVICE_CONNECT_WIFI,
    SERVICE_DISCONNECT_WIFI,
    SERVICE_GET_FIREWALL_RULES,
    SERVICE_GET_MCU_BATTERY_CONFIG,
    SERVICE_GET_MCU_OLED_CONFIG,
    SERVICE_GET_SAVED_NETWORKS,
    SERVICE_GET_SMS,
    SERVICE_KMWAN_GET_CONFIG,
    SERVICE_KMWAN_GET_STATUS,
    SERVICE_KMWAN_SET_CONFIG,
    SERVICE_KMWAN_SET_INTERFACE,
    SERVICE_KMWAN_SET_SENSITIVITY,
    SERVICE_MWAN3_GET_CONFIG,
    SERVICE_MWAN3_GET_STATUS,
    SERVICE_MWAN3_SET_CONFIG,
    SERVICE_MWAN3_SET_INTERFACE,
    SERVICE_PARENTAL_CONTROL_SET_FILTERING_MODE,
    SERVICE_PARENTAL_CONTROL_SET_GROUP_SCHEDULES,
    SERVICE_PARENTAL_CONTROL_SET_TEMPORARY_OVERRIDE,
    SERVICE_PARENTAL_CONTROL_UPDATE_SIGNATURES,
    SERVICE_PLAYGROUND,
    SERVICE_REFRESH_CLIENTS,
    SERVICE_REFRESH_SMS,
    SERVICE_REMOVE_FIREWALL_RULE,
    SERVICE_REMOVE_PORT_FORWARD,
    SERVICE_REMOVE_SAVED_NETWORK,
    SERVICE_REMOVE_SMS,
    SERVICE_SCAN_WIFI,
    SERVICE_SEND_SMS,
    SERVICE_SET_DMZ,
    SERVICE_SET_FAN_TEMPERATURE,
    SERVICE_SET_MCU_BATTERY_CONFIG,
    SERVICE_SET_MCU_OLED_CONFIG,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

    from .hub import GLinetHub


@dataclass(frozen=True)
class _ServiceSpec:
    """Declarative description of a GL.iNet service registration."""

    name: str
    handler: Callable[[ServiceCall], Any]
    schema: vol.Schema
    supports_response: SupportsResponse | None = None
    feature: str | None = None


def _enabled_features_from_entry(entry: Any) -> set[str]:
    if not entry:
        return set(FEATURE_OPTIONS)

    data = getattr(entry, "data", {})
    options = getattr(entry, "options", {})
    features = options.get(CONF_ENABLED_FEATURES) or data.get(CONF_ENABLED_FEATURES)

    if features is None:
        return set(FEATURE_OPTIONS)
    return set(features)


def _ensure_feature_enabled(hub: GLinetHub, feature: str, service_name: str) -> None:
    if not hub.feature_enabled(feature):
        raise ValueError(f"{service_name} is not enabled for router {hub.device_mac}")


def _feature_enabled_for_any_entry(entries: list[Any], feature: str) -> bool:
    return any(feature in _enabled_features_from_entry(entry) for entry in entries)


def _apply_specs(
    hass: HomeAssistant,
    specs: tuple[_ServiceSpec, ...],
    enabled: bool,
) -> None:
    for spec in specs:
        if enabled:
            kwargs: dict[str, Any] = {"schema": spec.schema}
            if spec.supports_response is not None:
                kwargs["supports_response"] = spec.supports_response
            hass.services.async_register(DOMAIN, spec.name, spec.handler, **kwargs)
        elif hass.services.has_service(DOMAIN, spec.name):
            hass.services.async_remove(DOMAIN, spec.name)


def _params_without_mac(call_data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in call_data.items() if k != CONF_MAC}


async def async_register_services(hass: HomeAssistant) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return

    async def async_set_fan_temperature(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        await hub.set_fan_temperature(call.data[ATTR_TEMPERATURE])

    async def async_refresh_clients(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        await hub.fetch_connected_devices()
        await hub.async_request_refresh()

    async def async_mwan3_get_config(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MWAN3, SERVICE_MWAN3_GET_CONFIG)
        return {"config": await hub.get_mwan3_config()}

    async def async_mwan3_get_status(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MWAN3, SERVICE_MWAN3_GET_STATUS)
        return {"status": await hub.get_mwan3_status()}

    async def async_mwan3_set_config(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MWAN3, SERVICE_MWAN3_SET_CONFIG)
        await hub.set_mwan3_config(dict(call.data[ATTR_CONFIG]))

    async def async_mwan3_set_interface(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MWAN3, SERVICE_MWAN3_SET_INTERFACE)
        await hub.set_mwan3_interface(dict(call.data[ATTR_INTERFACE]))

    async def async_kmwan_get_config(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_KMWAN, SERVICE_KMWAN_GET_CONFIG)
        return {"config": await hub.get_kmwan_config()}

    async def async_kmwan_get_status(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_KMWAN, SERVICE_KMWAN_GET_STATUS)
        return {"status": await hub.get_kmwan_status()}

    async def async_kmwan_set_config(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_KMWAN, SERVICE_KMWAN_SET_CONFIG)
        await hub.set_kmwan_config(dict(call.data[ATTR_CONFIG]))

    async def async_kmwan_set_interface(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_KMWAN, SERVICE_KMWAN_SET_INTERFACE)
        await hub.set_kmwan_interface(dict(call.data[ATTR_INTERFACE]))

    async def async_kmwan_set_sensitivity(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_KMWAN, SERVICE_KMWAN_SET_SENSITIVITY)
        await hub.set_kmwan_sensitivity(dict(call.data[ATTR_SENSITIVITY]))

    async def async_playground(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_PLAYGROUND, SERVICE_PLAYGROUND)
        method = call.data[ATTR_METHOD]
        body = call.data.get(ATTR_BODY)
        response = await hub.custom_request(method, body)
        if response is None:
            return {"error": "API invocation failed"}
        if isinstance(response, dict):
            return response
        return {"result": response}

    async def async_send_sms(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_SMS, "send_sms")
        recipient = call.data[ATTR_RECIPIENT]
        await hub.send_sms(recipient, call.data[ATTR_TEXT])

    async def async_refresh_sms(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_SMS, "refresh_sms")
        await hub.fetch_sms_messages()

    async def async_get_sms(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_SMS, "get_sms")
        await hub.fetch_sms_messages()
        return {
            "messages": [
                {
                    "id": msg.message_id,
                    "phone_number": msg.phone_number,
                    "direction": msg.direction.value,
                    "status": msg.status_label,
                    "text": msg.text,
                    "timestamp": msg.timestamp,
                }
                for msg in hub.sms_messages.values()
            ]
        }

    async def async_remove_sms(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_SMS, "remove_sms")
        await hub.remove_sms(
            scope=call.data[ATTR_SCOPE],
            message_id=call.data.get(ATTR_MESSAGE_ID),
        )

    async def async_scan_wifi(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_REPEATER, "scan_wifi")
        networks = await hub.scan_wifi_networks(
            all_band=call.data.get(ATTR_ALL_BAND, False),
            dfs=call.data.get(ATTR_DFS, False),
            refresh=call.data.get(ATTR_REFRESH, False),
        )
        return {
            "networks": [
                {
                    "ssid": network.ssid,
                    "bssid": network.bssid,
                    "signal": network.signal,
                    "band": network.band,
                    "channel": network.channel,
                    "encryption": network.encryption_type,
                    "saved": network.saved,
                }
                for network in networks
            ]
        }

    async def async_connect_wifi(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_REPEATER, "connect_wifi")
        await hub.connect_to_wifi(
            ssid=call.data[ATTR_SSID],
            password=call.data.get(ATTR_PASSWORD),
            remember=call.data.get(ATTR_REMEMBER, True),
            bssid=call.data.get(ATTR_BSSID),
        )

    async def async_disconnect_wifi(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_REPEATER, "disconnect_wifi")
        await hub.disconnect_wifi()

    async def async_get_saved_networks(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_REPEATER, "get_saved_networks")
        networks = await hub.get_saved_wifi_networks()
        return {
            "networks": [
                {
                    "ssid": network.get("ssid"),
                    "bssid": network.get("bssid"),
                    "protocol": network.get("protocol", "dhcp"),
                }
                for network in networks
            ]
        }

    async def async_remove_saved_network(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_REPEATER, "remove_saved_network")
        await hub.remove_saved_wifi_network(call.data[ATTR_SSID])

    async def async_add_firewall_rule(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_FIREWALL, "add_firewall_rule")
        await hub.add_firewall_rule(_params_without_mac(call.data))

    async def async_remove_firewall_rule(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_FIREWALL, "remove_firewall_rule")
        await hub.remove_firewall_rule(rule_id=call.data[ATTR_RULE_ID])

    async def async_get_firewall_rules(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_FIREWALL, "get_firewall_rules")
        return {"rules": await hub.get_firewall_rule_summaries()}

    async def async_add_port_forward(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_FIREWALL, "add_port_forward")
        await hub.add_port_forward(_params_without_mac(call.data))

    async def async_remove_port_forward(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_FIREWALL, "remove_port_forward")
        await hub.remove_port_forward(
            rule_id=call.data.get(ATTR_RULE_ID),
            remove_all=call.data.get(ATTR_REMOVE_ALL, False),
        )

    async def async_set_dmz(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_FIREWALL, "set_dmz")
        await hub.set_dmz_config(
            enabled=call.data[ATTR_ENABLED],
            dest_ip=call.data.get(ATTR_DEST_IP),
        )

    async def async_get_mcu_battery_config(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MCU_BATTERY, "get_mcu_battery_config")
        return {"config": await hub.get_mcu_battery_config()}

    async def async_set_mcu_battery_config(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MCU_BATTERY, "set_mcu_battery_config")
        config = {
            "capacity": {
                "enable": call.data[ATTR_CAPACITY_ENABLED],
                "value": call.data[ATTR_CAPACITY],
            },
            "temp_high": {
                "enable": call.data[ATTR_TEMP_HIGH_ENABLED],
                "value": call.data[ATTR_TEMP_HIGH],
            },
            "temp_low": {
                "enable": call.data[ATTR_TEMP_LOW_ENABLED],
                "value": call.data[ATTR_TEMP_LOW],
            },
        }
        await hub.set_mcu_battery_config(config)

    async def async_get_mcu_oled_config(call: ServiceCall) -> ServiceResponse:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MCU_OLED, "get_mcu_oled_config")
        return {"config": await hub.get_mcu_oled_config()}

    async def async_set_mcu_oled_config(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_MCU_OLED, "set_mcu_oled_config")
        screen_display = {
            key: call.data[key]
            for key in (
                ATTR_MAIN,
                ATTR_WIFI_PASSWORD,
                ATTR_WIFI_2G,
                ATTR_WIFI_5G,
                ATTR_LAN,
                ATTR_VPN,
                ATTR_CUSTOM,
                ATTR_CONTENT,
            )
            if key in call.data
        }
        await hub.set_mcu_oled_config(screen_display)

    async def async_parental_control_set_temporary_override(
        call: ServiceCall,
    ) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(
            hub,
            FEATURE_PARENTAL_CONTROL,
            "parental_control_set_temporary_override",
        )
        await hub.set_temporary_override(
            group_id=call.data[ATTR_GROUP_ID],
            enable=call.data[ATTR_ENABLED],
            duration=call.data.get(ATTR_DURATION, ""),
            rule_id=call.data[ATTR_RULE_ID],
        )

    async def async_parental_control_set_filtering_mode(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(
            hub,
            FEATURE_PARENTAL_CONTROL,
            "parental_control_set_filtering_mode",
        )
        await hub.set_parental_mode(call.data[ATTR_MODE])

    async def async_parental_control_update_signatures(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(
            hub,
            FEATURE_PARENTAL_CONTROL,
            "parental_control_update_signatures",
        )
        await hub.update_parental_signatures()

    async def async_access_control_set_mode(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(hub, FEATURE_PARENTAL_CONTROL, "access_control_set_mode")
        await hub.set_access_control_mode(call.data[ATTR_MODE])

    async def async_access_control_set_device_block(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(
            hub,
            FEATURE_PARENTAL_CONTROL,
            "access_control_set_device_block",
        )
        await hub.set_single_device_block(call.data[ATTR_SRC_MAC], call.data[ATTR_BLOCK])

    async def async_parental_control_set_group_schedules(call: ServiceCall) -> None:
        hub = _get_hub(hass, call.data)
        _ensure_feature_enabled(
            hub,
            FEATURE_PARENTAL_CONTROL,
            "parental_control_set_group_schedules",
        )
        await hub.set_group_schedules_enabled(
            call.data[ATTR_GROUP_ID],
            call.data[ATTR_ENABLED],
        )

    _SMS_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_SEND_SMS,
            async_send_sms,
            vol.Schema(
                {
                    vol.Required(ATTR_RECIPIENT): cv.string,
                    vol.Required(ATTR_TEXT): cv.string,
                }
            ),
            feature=FEATURE_SMS,
        ),
        _ServiceSpec(
            SERVICE_REFRESH_SMS,
            async_refresh_sms,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            feature=FEATURE_SMS,
        ),
        _ServiceSpec(
            SERVICE_GET_SMS,
            async_get_sms,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_SMS,
        ),
        _ServiceSpec(
            SERVICE_REMOVE_SMS,
            async_remove_sms,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_SCOPE, default=10): vol.In(
                        [0, 1, 2, 3, 4, 5, 10, 11, 12, 13]
                    ),
                    vol.Optional(ATTR_MESSAGE_ID): cv.string,
                }
            ),
            feature=FEATURE_SMS,
        ),
    )

    _REPEATER_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_SCAN_WIFI,
            async_scan_wifi,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Optional(ATTR_ALL_BAND, default=False): cv.boolean,
                    vol.Optional(ATTR_DFS, default=False): cv.boolean,
                    vol.Optional(ATTR_REFRESH, default=False): cv.boolean,
                }
            ),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_REPEATER,
        ),
        _ServiceSpec(
            SERVICE_CONNECT_WIFI,
            async_connect_wifi,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_SSID): cv.string,
                    vol.Optional(ATTR_PASSWORD): cv.string,
                    vol.Optional(ATTR_REMEMBER, default=True): cv.boolean,
                    vol.Optional(ATTR_BSSID): cv.string,
                }
            ),
            feature=FEATURE_REPEATER,
        ),
        _ServiceSpec(
            SERVICE_DISCONNECT_WIFI,
            async_disconnect_wifi,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            feature=FEATURE_REPEATER,
        ),
        _ServiceSpec(
            SERVICE_GET_SAVED_NETWORKS,
            async_get_saved_networks,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_REPEATER,
        ),
        _ServiceSpec(
            SERVICE_REMOVE_SAVED_NETWORK,
            async_remove_saved_network,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_SSID): cv.string,
                }
            ),
            feature=FEATURE_REPEATER,
        ),
    )

    _FIREWALL_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_ADD_FIREWALL_RULE,
            async_add_firewall_rule,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_NAME): cv.string,
                    vol.Required(ATTR_SRC): cv.string,
                    vol.Optional(ATTR_SRC_IP): cv.string,
                    vol.Optional(ATTR_SRC_MAC): cv.string,
                    vol.Optional(ATTR_SRC_PORT): cv.string,
                    vol.Required(ATTR_PROTO): cv.string,
                    vol.Required(ATTR_DEST): cv.string,
                    vol.Optional(ATTR_DEST_IP): cv.string,
                    vol.Optional(ATTR_DEST_PORT): cv.string,
                    vol.Required(ATTR_TARGET): cv.string,
                    vol.Optional(ATTR_ENABLED, default=True): cv.boolean,
                }
            ),
            feature=FEATURE_FIREWALL,
        ),
        _ServiceSpec(
            SERVICE_GET_FIREWALL_RULES,
            async_get_firewall_rules,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_FIREWALL,
        ),
        _ServiceSpec(
            SERVICE_REMOVE_FIREWALL_RULE,
            async_remove_firewall_rule,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_RULE_ID): cv.string,
                }
            ),
            feature=FEATURE_FIREWALL,
        ),
        _ServiceSpec(
            SERVICE_ADD_PORT_FORWARD,
            async_add_port_forward,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_NAME): cv.string,
                    vol.Required(ATTR_SRC): cv.string,
                    vol.Required(ATTR_SRC_DPORT): cv.string,
                    vol.Required(ATTR_PROTO): cv.string,
                    vol.Required(ATTR_DEST): cv.string,
                    vol.Required(ATTR_DEST_IP): cv.string,
                    vol.Required(ATTR_DEST_PORT): cv.string,
                    vol.Optional(ATTR_ENABLED, default=True): cv.boolean,
                }
            ),
            feature=FEATURE_FIREWALL,
        ),
        _ServiceSpec(
            SERVICE_REMOVE_PORT_FORWARD,
            async_remove_port_forward,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Optional(ATTR_RULE_ID): cv.string,
                    vol.Optional(ATTR_REMOVE_ALL, default=False): cv.boolean,
                }
            ),
            feature=FEATURE_FIREWALL,
        ),
        _ServiceSpec(
            SERVICE_SET_DMZ,
            async_set_dmz,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_ENABLED): cv.boolean,
                    vol.Optional(ATTR_DEST_IP): cv.string,
                }
            ),
            feature=FEATURE_FIREWALL,
        ),
    )

    _KMWAN_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_KMWAN_GET_CONFIG,
            async_kmwan_get_config,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_KMWAN,
        ),
        _ServiceSpec(
            SERVICE_KMWAN_GET_STATUS,
            async_kmwan_get_status,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_KMWAN,
        ),
        _ServiceSpec(
            SERVICE_KMWAN_SET_CONFIG,
            async_kmwan_set_config,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_CONFIG): object,
                }
            ),
            feature=FEATURE_KMWAN,
        ),
        _ServiceSpec(
            SERVICE_KMWAN_SET_INTERFACE,
            async_kmwan_set_interface,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_INTERFACE): object,
                }
            ),
            feature=FEATURE_KMWAN,
        ),
        _ServiceSpec(
            SERVICE_KMWAN_SET_SENSITIVITY,
            async_kmwan_set_sensitivity,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_SENSITIVITY): object,
                }
            ),
            feature=FEATURE_KMWAN,
        ),
    )

    _MWAN3_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_MWAN3_GET_CONFIG,
            async_mwan3_get_config,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_MWAN3,
        ),
        _ServiceSpec(
            SERVICE_MWAN3_GET_STATUS,
            async_mwan3_get_status,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_MWAN3,
        ),
        _ServiceSpec(
            SERVICE_MWAN3_SET_CONFIG,
            async_mwan3_set_config,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_CONFIG): object,
                }
            ),
            feature=FEATURE_MWAN3,
        ),
        _ServiceSpec(
            SERVICE_MWAN3_SET_INTERFACE,
            async_mwan3_set_interface,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_INTERFACE): object,
                }
            ),
            feature=FEATURE_MWAN3,
        ),
    )

    _MCU_BATTERY_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_GET_MCU_BATTERY_CONFIG,
            async_get_mcu_battery_config,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_MCU_BATTERY,
        ),
        _ServiceSpec(
            SERVICE_SET_MCU_BATTERY_CONFIG,
            async_set_mcu_battery_config,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_CAPACITY_ENABLED): cv.boolean,
                    vol.Required(ATTR_CAPACITY): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=100)
                    ),
                    vol.Required(ATTR_TEMP_HIGH_ENABLED): cv.boolean,
                    vol.Required(ATTR_TEMP_HIGH): vol.Coerce(int),
                    vol.Required(ATTR_TEMP_LOW_ENABLED): cv.boolean,
                    vol.Required(ATTR_TEMP_LOW): vol.Coerce(int),
                }
            ),
            feature=FEATURE_MCU_BATTERY,
        ),
    )

    _MCU_OLED_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_GET_MCU_OLED_CONFIG,
            async_get_mcu_oled_config,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_MCU_OLED,
        ),
        _ServiceSpec(
            SERVICE_SET_MCU_OLED_CONFIG,
            async_set_mcu_oled_config,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Optional(ATTR_MAIN): cv.boolean,
                    vol.Optional(ATTR_WIFI_PASSWORD): cv.boolean,
                    vol.Optional(ATTR_WIFI_2G): cv.boolean,
                    vol.Optional(ATTR_WIFI_5G): cv.boolean,
                    vol.Optional(ATTR_LAN): cv.boolean,
                    vol.Optional(ATTR_VPN): cv.boolean,
                    vol.Optional(ATTR_CUSTOM): cv.boolean,
                    vol.Optional(ATTR_CONTENT): cv.string,
                }
            ),
            feature=FEATURE_MCU_OLED,
        ),
    )

    _PARENTAL_CONTROL_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_PARENTAL_CONTROL_SET_TEMPORARY_OVERRIDE,
            async_parental_control_set_temporary_override,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_GROUP_ID): cv.string,
                    vol.Required(ATTR_ENABLED): cv.boolean,
                    vol.Required(ATTR_RULE_ID): cv.string,
                    vol.Optional(ATTR_DURATION, default=""): cv.string,
                }
            ),
            feature=FEATURE_PARENTAL_CONTROL,
        ),
        _ServiceSpec(
            SERVICE_PARENTAL_CONTROL_SET_FILTERING_MODE,
            async_parental_control_set_filtering_mode,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_MODE): vol.Coerce(int),
                }
            ),
            feature=FEATURE_PARENTAL_CONTROL,
        ),
        _ServiceSpec(
            SERVICE_PARENTAL_CONTROL_UPDATE_SIGNATURES,
            async_parental_control_update_signatures,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
            feature=FEATURE_PARENTAL_CONTROL,
        ),
        _ServiceSpec(
            SERVICE_ACCESS_CONTROL_SET_MODE,
            async_access_control_set_mode,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_MODE): vol.In(["black", "white"]),
                }
            ),
            feature=FEATURE_PARENTAL_CONTROL,
        ),
        _ServiceSpec(
            SERVICE_ACCESS_CONTROL_SET_DEVICE_BLOCK,
            async_access_control_set_device_block,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_SRC_MAC): cv.string,
                    vol.Required(ATTR_BLOCK): cv.boolean,
                }
            ),
            feature=FEATURE_PARENTAL_CONTROL,
        ),
        _ServiceSpec(
            SERVICE_PARENTAL_CONTROL_SET_GROUP_SCHEDULES,
            async_parental_control_set_group_schedules,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_GROUP_ID): cv.string,
                    vol.Required(ATTR_ENABLED): cv.boolean,
                }
            ),
            feature=FEATURE_PARENTAL_CONTROL,
        ),
    )

    _PLAYGROUND_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_PLAYGROUND,
            async_playground,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_METHOD): cv.string,
                    vol.Optional(ATTR_BODY): object,
                }
            ),
            supports_response=SupportsResponse.ONLY,
            feature=FEATURE_PLAYGROUND,
        ),
    )

    _UNCONDITIONAL_SPECS: tuple[_ServiceSpec, ...] = (
        _ServiceSpec(
            SERVICE_SET_FAN_TEMPERATURE,
            async_set_fan_temperature,
            vol.Schema(
                {
                    vol.Optional(CONF_MAC): cv.string,
                    vol.Required(ATTR_TEMPERATURE): vol.All(
                        vol.Coerce(int), vol.Range(min=70, max=90)
                    ),
                }
            ),
        ),
        _ServiceSpec(
            SERVICE_REFRESH_CLIENTS,
            async_refresh_clients,
            vol.Schema({vol.Optional(CONF_MAC): cv.string}),
        ),
    )

    _apply_specs(hass, _SMS_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_SMS))
    _apply_specs(
        hass, _REPEATER_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_REPEATER)
    )
    _apply_specs(
        hass, _FIREWALL_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_FIREWALL)
    )
    _apply_specs(hass, _KMWAN_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_KMWAN))
    _apply_specs(hass, _MWAN3_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_MWAN3))
    _apply_specs(
        hass, _MCU_BATTERY_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_MCU_BATTERY)
    )
    _apply_specs(
        hass, _MCU_OLED_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_MCU_OLED)
    )
    _apply_specs(
        hass,
        _PARENTAL_CONTROL_SPECS,
        _feature_enabled_for_any_entry(entries, FEATURE_PARENTAL_CONTROL),
    )
    _apply_specs(
        hass, _PLAYGROUND_SPECS, _feature_enabled_for_any_entry(entries, FEATURE_PLAYGROUND)
    )
    _apply_specs(hass, _UNCONDITIONAL_SPECS, True)


def _get_hub(hass: HomeAssistant, call_data: dict[str, Any]) -> GLinetHub:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ValueError("No GL.iNet config entries are loaded")

    target_mac = call_data.get(CONF_MAC)
    for config_entry in entries:
        hub: GLinetHub | None = getattr(config_entry, "runtime_data", None)
        if hub is None:
            continue
        if target_mac is None or hub.device_mac.lower() == str(target_mac).lower():
            return hub
    raise ValueError(f"No GL.iNet router found for MAC address {target_mac}")
