from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .api import APIClientError, GLinetApiClient, NonZeroResponse
from .const import (
    API_PATH,
    CONF_ADD_ALL_DEVICES,
    CONF_CLEANUP_DEVICES,
    CONF_ENABLED_FEATURES,
    CONF_PARALLEL_REQUESTS,
    CONF_SCAN_INTERVAL,
    CONF_TITLE,
    CONF_UNKNOWN_DEVICES_FILTER_MANUAL,
    CONF_UNKNOWN_DEVICES_FILTER_MODE,
    CONF_UNKNOWN_DEVICES_FILTER_SELECT,
    CONF_VERIFY_SSL,
    CONF_WAN_STATUS_MONITORS,
    DEFAULT_PARALLEL_REQUESTS,
    DEFAULT_PASSWORD,
    DEFAULT_UNKNOWN_DEVICES_FILTER_MODE,
    DEFAULT_URL,
    DEFAULT_USERNAME,
    DOMAIN,
    FEATURE_ADGUARD,
    FEATURE_CELLULAR,
    FEATURE_FIREWALL,
    FEATURE_KMWAN,
    FEATURE_MCU_BATTERY,
    FEATURE_MCU_OLED,
    FEATURE_MWAN3,
    FEATURE_OVPN_CLIENT,
    FEATURE_OVPN_SERVER,
    FEATURE_PARENTAL_CONTROL,
    FEATURE_PLAYGROUND,
    FEATURE_REPEATER,
    FEATURE_SMS,
    FEATURE_TAILSCALE,
    FEATURE_WG_CLIENT,
    FEATURE_WG_SERVER,
    FEATURE_ZEROTIER,
    INTEGRATION_NAME,
    WAN_INTERFACE_NAMES,
)
from .utils import compute_mac_offset

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

_LOGGER = logging.getLogger(__name__)

FEATURE_OPTIONS: list[selector.SelectOptionDict] = [
    {"label": "Cellular", "value": FEATURE_CELLULAR},
    {"label": "Repeater", "value": FEATURE_REPEATER},
    {"label": "SMS", "value": FEATURE_SMS},
    {"label": "Tailscale", "value": FEATURE_TAILSCALE},
    {"label": "WireGuard Client", "value": FEATURE_WG_CLIENT},
    {"label": "WireGuard Server", "value": FEATURE_WG_SERVER},
    {"label": "OpenVPN Client", "value": FEATURE_OVPN_CLIENT},
    {"label": "OpenVPN Server", "value": FEATURE_OVPN_SERVER},
    {"label": "ZeroTier (Requires Network ID setup on router)", "value": FEATURE_ZEROTIER},
    {"label": "KMWan", "value": FEATURE_KMWAN},
    {"label": "MWan3", "value": FEATURE_MWAN3},
    {"label": "AdGuard Home", "value": FEATURE_ADGUARD},
    {"label": "Firewall", "value": FEATURE_FIREWALL},
    {"label": "MCU Battery", "value": FEATURE_MCU_BATTERY},
    {"label": "MCU OLED", "value": FEATURE_MCU_OLED},
    {"label": "Parental & Access Control", "value": FEATURE_PARENTAL_CONTROL},
    {"label": "API Playground", "value": FEATURE_PLAYGROUND},
]
DEFAULT_ENABLED_FEATURES = [
    FEATURE_CELLULAR,
    FEATURE_REPEATER,
    FEATURE_SMS,
    FEATURE_TAILSCALE,
    FEATURE_WG_CLIENT,
    FEATURE_WG_SERVER,
    FEATURE_OVPN_CLIENT,
    FEATURE_OVPN_SERVER,
    FEATURE_ADGUARD,
    FEATURE_FIREWALL,
    FEATURE_MCU_BATTERY,
    FEATURE_MCU_OLED,
    FEATURE_PARENTAL_CONTROL,
]
DEFAULT_WAN_INTERFACES = ["wan", "wwan", "tethering", "modem_0001", "secondwan"]
WAN_STATUS_PROTOCOLS = [("ipv4", "IPv4"), ("ipv6", "IPv6")]


def _wan_monitor_key(interface: str, protocol: str) -> str:
    return f"{interface}:{protocol}"


def _wan_interface_label(interface: str) -> str:
    return WAN_INTERFACE_NAMES.get(interface, interface)


def _wan_monitor_options(interfaces: list[str]) -> list[selector.SelectOptionDict]:
    return [
        {
            "label": f"{_wan_interface_label(interface)} {label}",
            "value": _wan_monitor_key(interface, protocol),
        }
        for interface in interfaces
        for protocol, label in WAN_STATUS_PROTOCOLS
    ]


def _default_wan_status_monitors(interfaces: list[str]) -> list[str]:
    return [
        _wan_monitor_key(interface, protocol)
        for interface in interfaces
        for protocol, _ in WAN_STATUS_PROTOCOLS
    ]


def _wan_interfaces_from_monitors(monitors: list[str]) -> list[str]:
    interfaces = []
    for monitor in monitors:
        interface, separator, protocol = monitor.partition(":")
        if separator and protocol in {"ipv4", "ipv6"} and interface not in interfaces:
            interfaces.append(interface)
    return interfaces


def _config_schema(
    defaults: dict[str, Any] | None = None,
    wan_interfaces: list[str] | None = None,
    discovered_devices: dict[str, str] | None = None,
) -> vol.Schema:
    defaults = defaults or {}
    wan_interfaces = wan_interfaces or DEFAULT_WAN_INTERFACES
    selected_interfaces = _wan_interfaces_from_monitors(defaults.get(CONF_WAN_STATUS_MONITORS, []))
    wan_interfaces = [*dict.fromkeys([*wan_interfaces, *selected_interfaces])]

    schema_dict = {
        vol.Required(CONF_HOST, default=DEFAULT_URL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        ),
        vol.Required(CONF_PASSWORD, default=DEFAULT_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_VERIFY_SSL, default=False): bool,
        vol.Optional(
            CONF_PARALLEL_REQUESTS,
            default=defaults.get(CONF_PARALLEL_REQUESTS, DEFAULT_PARALLEL_REQUESTS),
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_CONSIDER_HOME,
            default=DEFAULT_CONSIDER_HOME.total_seconds(),
        ): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=900)),
        vol.Optional(
            CONF_ENABLED_FEATURES,
            default=DEFAULT_ENABLED_FEATURES,
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=FEATURE_OPTIONS,
                multiple=True,
            )
        ),
        vol.Optional(
            CONF_WAN_STATUS_MONITORS,
            default=defaults.get(
                CONF_WAN_STATUS_MONITORS,
                _default_wan_status_monitors(wan_interfaces),
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_wan_monitor_options(wan_interfaces),
                multiple=True,
            )
        ),
        vol.Optional(
            CONF_SCAN_INTERVAL,
            default=30,
        ): vol.All(vol.Coerce(int), vol.Clamp(min=10, max=300)),
        vol.Optional(CONF_ADD_ALL_DEVICES, default=False): bool,
        vol.Optional(
            CONF_CLEANUP_DEVICES,
            default=0,
        ): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=10080)),
        vol.Optional(
            CONF_UNKNOWN_DEVICES_FILTER_MODE,
            default=defaults.get(
                CONF_UNKNOWN_DEVICES_FILTER_MODE,
                DEFAULT_UNKNOWN_DEVICES_FILTER_MODE,
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[  # type: ignore[typeddict-item]
                    {"value": "blacklist", "label": "Blacklist"},
                    {"value": "whitelist", "label": "Whitelist"},
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }

    if discovered_devices:
        schema_dict[
            vol.Optional(
                CONF_UNKNOWN_DEVICES_FILTER_SELECT,
                default=defaults.get(CONF_UNKNOWN_DEVICES_FILTER_SELECT, []),
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[{"value": k, "label": v} for k, v in discovered_devices.items()],  # type: ignore[typeddict-item]
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    schema_dict[
        vol.Optional(
            CONF_UNKNOWN_DEVICES_FILTER_MANUAL,
            default="",
        )
    ] = selector.TextSelector(
        selector.TextSelectorConfig(
            multiline=True,
            type=selector.TextSelectorType.TEXT,
        )
    )

    return vol.Schema(schema_dict)


STEP_USER_DATA_SCHEMA = _config_schema()


class SetupHub:
    def __init__(self, host: str, hass: HomeAssistant, verify_ssl: bool = False) -> None:
        self.host = host
        self.username = DEFAULT_USERNAME
        self.router = GLinetApiClient(
            base_url=f"{host}{API_PATH}",
            session=async_get_clientsession(hass),
            verify_ssl=verify_ssl,
        )
        self.router_mac = ""
        self.router_model = ""
        self.wan_interfaces: list[str] = DEFAULT_WAN_INTERFACES

    async def check_reachable(self) -> bool:
        try:
            return await self.router.is_router_reachable(self.username)
        except (ConnectionError, TypeError, TimeoutError, OSError):
            _LOGGER.exception("Failed to connect to %s", self.host)
            return False

    async def attempt_login(self, password: str) -> bool:
        try:
            await self.router.authenticate(self.username, password)
            info = await self.router.system.get_info()
        except (ConnectionRefusedError, TimeoutError, OSError) as exc:
            _LOGGER.exception("Connection failure during GL.iNet validation")
            raise ConnectionError from exc
        except NonZeroResponse:
            _LOGGER.info("Failed to authenticate with GL.iNet router during validation")
            return False

        self.router_mac = str(info.mac)
        self.router_model = str(info.model)
        try:
            kmwan_status = await self.router.system.get_kmwan_status()
        except (APIClientError, ConnectionError, TimeoutError, OSError, ValueError):
            _LOGGER.debug("Unable to fetch WAN interfaces during setup", exc_info=True)
        else:
            interfaces = [
                str(interface.get("interface"))
                for interface in kmwan_status.get("interfaces", [])
                if isinstance(interface, dict) and interface.get("interface")
            ]
            if interfaces:
                self.wan_interfaces = interfaces
        return self.router.logged_in


async def process_user_input(
    data: dict[str, Any], hass: HomeAssistant, raise_on_invalid_auth: bool = True
) -> dict[str, Any]:
    verify_ssl_choice = data.get(CONF_VERIFY_SSL, False)
    hub = SetupHub(data[CONF_HOST], hass, verify_ssl=verify_ssl_choice)
    if not await hub.check_reachable():
        raise CannotConnect

    try:
        valid_auth = await hub.attempt_login(data.get(CONF_PASSWORD, DEFAULT_PASSWORD))
    except ConnectionError:
        raise CannotConnect from None
    if raise_on_invalid_auth and not valid_auth:
        raise InvalidAuth

    return {
        CONF_TITLE: f"{INTEGRATION_NAME} {hub.router_model.upper()}",
        CONF_MAC: hub.router_mac,
        "data": {
            CONF_USERNAME: DEFAULT_USERNAME,
            CONF_HOST: data[CONF_HOST],
            CONF_PASSWORD: data.get(CONF_PASSWORD, DEFAULT_PASSWORD) if valid_auth else "",
            CONF_VERIFY_SSL: verify_ssl_choice,
            CONF_CONSIDER_HOME: data.get(
                CONF_CONSIDER_HOME,
                DEFAULT_CONSIDER_HOME.total_seconds(),
            ),
            CONF_ENABLED_FEATURES: data.get(
                CONF_ENABLED_FEATURES,
                DEFAULT_ENABLED_FEATURES,
            ),
            CONF_WAN_STATUS_MONITORS: data.get(
                CONF_WAN_STATUS_MONITORS,
                _default_wan_status_monitors(hub.wan_interfaces),
            ),
            CONF_SCAN_INTERVAL: data.get(
                CONF_SCAN_INTERVAL,
                30,
            ),
            CONF_ADD_ALL_DEVICES: data.get(CONF_ADD_ALL_DEVICES, False),
            CONF_CLEANUP_DEVICES: data.get(CONF_CLEANUP_DEVICES, 0),
            CONF_UNKNOWN_DEVICES_FILTER_MODE: data.get(
                CONF_UNKNOWN_DEVICES_FILTER_MODE,
                DEFAULT_UNKNOWN_DEVICES_FILTER_MODE,
            ),
            CONF_UNKNOWN_DEVICES_FILTER_SELECT: data.get(
                CONF_UNKNOWN_DEVICES_FILTER_SELECT,
                [],
            ),
            CONF_UNKNOWN_DEVICES_FILTER_MANUAL: data.get(
                CONF_UNKNOWN_DEVICES_FILTER_MANUAL,
                "",
            ),
            CONF_PARALLEL_REQUESTS: data.get(
                CONF_PARALLEL_REQUESTS,
                DEFAULT_PARALLEL_REQUESTS,
            ),
        },
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered_data: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await process_user_input(user_input, self.hass)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                unique_id = format_mac(info[CONF_MAC])
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info[CONF_TITLE], data=info["data"])

        defaults = user_input or self._discovered_data or {}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _config_schema(defaults),
                defaults,
            ),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        discovery_input = {CONF_HOST: f"http://{discovery_info.ip}"}
        self._async_abort_entries_match(discovery_input)

        unique_id = compute_mac_offset(discovery_info.macaddress, -1).lower()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        if {unique_id, format_mac(discovery_info.macaddress)}.intersection(
            self._async_current_ids(include_ignore=True)
        ):
            raise AbortFlow("already_configured")

        try:
            entry = await process_user_input(
                discovery_input,
                hass=self.hass,
                raise_on_invalid_auth=False,
            )
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")

        self._discovered_data = entry["data"]
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(_: config_entries.ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await process_user_input(user_input, self.hass)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="",
                    data=self.config_entry.options | info["data"],
                )

        defaults = {**self.config_entry.data, **self.config_entry.options}
        wan_interfaces = None
        discovered_devices = {}
        hub = getattr(self.config_entry, "runtime_data", None)
        if hub is not None:
            wan_interfaces = [
                str(interface.get("interface"))
                for interface in hub.kmwan_status.get("interfaces", [])
                if isinstance(interface, dict) and interface.get("interface")
            ]
            for mac, dev in hub._devices.items():
                if not dev.is_known:
                    name = dev.name or mac
                    discovered_devices[mac] = f"{name} ({mac})"

        current_selected = defaults.get(CONF_UNKNOWN_DEVICES_FILTER_SELECT, [])
        for mac in current_selected:
            if mac not in discovered_devices:
                discovered_devices[mac] = mac

        data_schema = self.add_suggested_values_to_schema(
            _config_schema(defaults, wan_interfaces or None, discovered_devices or None),
            defaults,
        )
        return self.async_show_form(step_id="init", data_schema=data_schema, errors=errors)


class CannotConnect(HomeAssistantError):
    pass


class InvalidAuth(HomeAssistantError):
    pass
