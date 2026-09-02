from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

from aiohttp import ClientError
from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
)
from homeassistant.components.device_tracker import (
    DOMAIN as TRACKER_DOMAIN,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .api import (
    APIClientError,
    GLinetApiClient,
    NonZeroResponse,
    TailscaleConnection,
    TokenError,
)
from .api.const import FIRMWARE_4_9
from .api.exceptions import AuthenticationError
from .api.models import RouterStatus
from .api.utils import decode_firmware_version
from .const import (
    API_PATH,
    CONF_ADD_ALL_DEVICES,
    CONF_CLEANUP_DEVICES,
    CONF_ENABLED_FEATURES,
    CONF_PARALLEL_REQUESTS,
    CONF_SCAN_INTERVAL,
    CONF_UNKNOWN_DEVICES_FILTER_MANUAL,
    CONF_UNKNOWN_DEVICES_FILTER_MODE,
    CONF_UNKNOWN_DEVICES_FILTER_SELECT,
    CONF_VERIFY_SSL,
    CONF_WAN_STATUS_MONITORS,
    DEFAULT_PARALLEL_REQUESTS,
    DEFAULT_USERNAME,
    DOMAIN,
    FEATURE_ADGUARD,
    FEATURE_CELLULAR,
    FEATURE_FIREWALL,
    FEATURE_MCU_BATTERY,
    FEATURE_MCU_OLED,
    FEATURE_OPTIONS,
    FEATURE_OVPN_CLIENT,
    FEATURE_OVPN_SERVER,
    FEATURE_PARENTAL_CONTROL,
    FEATURE_REPEATER,
    FEATURE_SMS,
    FEATURE_TAILSCALE,
    FEATURE_WG_CLIENT,
    FEATURE_WG_SERVER,
    FEATURE_ZEROTIER,
)
from .hub_helpers import (
    _FIRMWARE_INFO_ALIASES,
    EntityCleanupRule,
    _extract_access_macs,
    _merge_modem_lists,
    _modem_key,
    _normalise_traffic_config,
    _resolve_access_mode,
    _select_sms_modem,
    _sms_status_is_read,
)
from .models import (
    AdGuardStatus,
    ClientDeviceInfo,
    FanStatus,
    OpenVpnClient,
    OpenVpnServerStatus,
    ParentalGroup,
    ParentalStatus,
    RepeaterState,
    RepeaterStatus,
    ScannedNetwork,
    SmsMessage,
    VpnTunnel,
    WifiInterface,
    WireGuardClient,
    WireGuardServerStatus,
    ZeroTierStatus,
)
from .utils import compute_mac_offset, get_first_int, pick_first

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_registry import RegistryEntry

_LOGGER = logging.getLogger(__name__)
DEFAULT_SCAN_INTERVAL = 30
T = TypeVar("T")


class GLinetHub(DataUpdateCoordinator[None]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        settings = dict(entry.data) | dict(entry.options)
        scan_seconds = int(settings.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_seconds),
        )
        self._entry = entry
        self._options = dict(entry.options)
        self._settings = dict(entry.data) | dict(entry.options)
        self._host: str = self._settings[CONF_HOST]
        self._api: GLinetApiClient | None = None

        self._factory_mac = "UNKNOWN"
        self._model = "UNKNOWN"
        self._sw_version = "UNKNOWN"

        self._devices: dict[str, ClientDeviceInfo] = {}
        self._all_connected_clients: dict[str, dict[str, Any]] = {}
        self._wifi_ifaces: dict[str, WifiInterface] = {}
        self._system_status: RouterStatus | None = None
        self._kmwan_status: dict[str, Any] = {}
        self._cellular_status: dict[str, Any] = {}
        self._modems: dict[str, dict[str, Any]] = {}
        self._cached_modem_info: dict[str, Any] | None = None
        self._default_modem_bus: str | None = None
        self._default_modem_slot: int | str | None = None
        self._traffic_sim_data: dict[int, dict[str, Any]] = {}
        self._traffic_config_save_to_flash: bool | None = None
        self._entity_cleanup_rules: list[EntityCleanupRule] = []
        self._wireguard_clients: dict[int, WireGuardClient] = {}
        self._wireguard_connections: list[WireGuardClient] | None = None
        self._vpn_tunnels: dict[int, VpnTunnel] = {}
        self._vpn_tunnel_connections: list[VpnTunnel] | None = None
        self._tailscale_config: dict[str, Any] = {}
        self._tailscale_connection: bool | None = None
        self._sms_messages: dict[str, SmsMessage] = {}
        self._repeater_status: RepeaterStatus | None = None
        self._repeater_config: dict[str, Any] = {}
        self._scanned_networks: list[ScannedNetwork] = []
        self._last_wifi_scan: datetime | None = None
        self._saved_networks: list[dict[str, Any]] = []
        self._fan_status: FanStatus | None = None
        self._wg_server_status: dict[str, Any] = {}
        self._wg_server_peers: list[dict[str, Any]] = []
        self._ovpn_clients: dict[str, OpenVpnClient] = {}
        self._ovpn_connections: list[OpenVpnClient] | None = None
        self._ovpn_server_status: dict[str, Any] = {}
        self._ovpn_server_users: list[dict[str, Any]] = []
        self._ovpn_raw_clients: dict[str, dict[str, Any]] = {}
        self._ovpn_client_status: dict[str, Any] = {}
        self._upgrade_info: dict[str, Any] = {}
        self._upgrade_config: dict[str, Any] = {}
        self._upgrade_status: dict[str, Any] = {}
        self._last_upgrade_check: datetime | None = None
        self._zerotier_status: ZeroTierStatus | None = None
        self._led_enabled: bool | None = None
        self._adguard_status: AdGuardStatus | None = None
        self._firewall_rules: list[dict[str, Any]] = []
        self._mcu_battery_config: dict[str, Any] = {}
        self._mcu_oled_config: dict[str, Any] = {}
        self._dmz_config: dict[str, Any] = {}
        self._port_forwards: list[dict[str, Any]] = []
        self._wan_access: dict[str, Any] = {}
        self._zone_list: dict[str, Any] = {}
        self._access_control_config: dict[str, Any] = {}
        self._access_control_mode: str = "black"
        self._black_mac: list[str] = []
        self._white_mac: list[str] = []
        self._parental_status: ParentalStatus = ParentalStatus()

        self._late_init_complete = False
        self._connect_error = False
        self._token_error = False

    async def _async_update_data(self) -> None:
        try:
            await self.fetch_all_data()
            await self._async_cleanup_stale_devices()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    @property
    def enabled_features(self) -> set[str]:
        return set(self._settings.get(CONF_ENABLED_FEATURES, FEATURE_OPTIONS))

    def feature_enabled(self, feature: str) -> bool:
        return feature in self.enabled_features

    @property
    def parallel_requests(self) -> bool:
        return bool(self._settings.get(CONF_PARALLEL_REQUESTS, DEFAULT_PARALLEL_REQUESTS))

    @staticmethod
    def _extract_mac_from_entry(entry: RegistryEntry) -> str | None:
        if entry.domain == TRACKER_DOMAIN:
            return entry.unique_id
        if entry.unique_id.startswith("glinet_client_sensor/"):
            return entry.unique_id.split("/")[1]
        if entry.unique_id.startswith(("glinet_switch/", "glinet_select/")):
            parts = entry.unique_id.split("/")
            if len(parts) >= 3 and parts[2] in {
                "internet_access",
                "parental_control_group",
            }:
                return parts[1]
        return None

    def _wan_status_entity_selected(self, unique_id: str) -> bool:
        prefix = f"glinet_sensor/{self.device_mac}/"

        cellular_ip_map = {
            f"{prefix}cellular_ipv4": "modem_0001:ipv4",
            f"{prefix}cellular_ipv6": "modem_0001:ipv6",
        }
        if unique_id in cellular_ip_map:
            monitors = self.wan_status_monitors
            if monitors is None:
                return True
            return cellular_ip_map[unique_id] in monitors

        wan_prefix = f"{prefix}wan_status_"
        if not unique_id.startswith(wan_prefix):
            return True

        monitors = self.wan_status_monitors
        if monitors is None:
            return True

        selected_parts = []
        for monitor in monitors:
            interface, separator, protocol = monitor.partition(":")
            if separator and protocol in {"ipv4", "ipv6"} and interface:
                selected_parts.append((interface, protocol))

        suffix = unique_id.removeprefix(wan_prefix)
        return any(
            suffix == interface or suffix == f"{interface}_{protocol}"
            for interface, protocol in selected_parts
        )

    def _is_legacy_cellular_signal_sensor(self, unique_id: str) -> bool:
        prefix = f"glinet_sensor/{self.device_mac}/"
        if not unique_id.startswith(prefix):
            return False
        suffix = unique_id.removeprefix(prefix)
        return suffix in {"cellular_signal", "cellular_rssi", "cellular_network"}

    async def async_initialize_hub(self) -> None:
        if not self._late_init_complete:
            await self._async_load_router_info()

        entity_registry = er.async_get(self.hass)
        track_entries: list[RegistryEntry] = er.async_entries_for_config_entry(
            entity_registry, self._entry.entry_id
        )

        feature_map = {
            FEATURE_CELLULAR: ["cellular_"],
            FEATURE_SMS: ["sms_messages", "unread_messages"],
            FEATURE_REPEATER: [
                "repeater_",
                "wifi_network",
                "scan_wifi",
                "disconnect_repeater",
            ],
            FEATURE_TAILSCALE: ["tailscale"],
            FEATURE_WG_CLIENT: [
                "wireguard_client",
                "vpn_client",
                "wg_client",
                "vpn_tunnel/wg",
                "vpn_tunnel/unknown",
            ],
            FEATURE_WG_SERVER: [
                "wg_server",
            ],
            FEATURE_OVPN_CLIENT: [
                "ovpn_client",
                "vpn_tunnel/ovpn",
                "vpn_tunnel/unknown",
            ],
            FEATURE_OVPN_SERVER: [
                "ovpn_server",
            ],
            FEATURE_ADGUARD: [
                "adguard",
            ],
            FEATURE_ZEROTIER: [
                "zerotier",
            ],
            FEATURE_FIREWALL: [
                "firewall",
                "dmz",
                "port_forwards",
                "wan_access",
            ],
            FEATURE_MCU_BATTERY: [
                "battery",
                "mcu_battery",
            ],
            FEATURE_MCU_OLED: [
                "oled",
                "mcu_oled",
            ],
            FEATURE_PARENTAL_CONTROL: [
                "parental_control",
                "access_control",
                "black_white_list",
                "black_white",
                "internet_access",
            ],
        }

        for entry in track_entries:
            removed = False
            for feature, keywords in feature_map.items():
                if not self.feature_enabled(feature):
                    if any(k in entry.unique_id for k in keywords):
                        _LOGGER.debug(
                            "Removing orphan entity %s (feature %s disabled)",
                            entry.entity_id,
                            feature,
                        )
                        entity_registry.async_remove(entry.entity_id)
                        removed = True
                        break

            if not removed and not self._wan_status_entity_selected(entry.unique_id):
                _LOGGER.debug(
                    "Removing unselected WAN status entity %s",
                    entry.entity_id,
                )
                entity_registry.async_remove(entry.entity_id)
                removed = True

            if (
                not removed
                and self.is_firmware_4_9_or_above
                and self._is_legacy_cellular_signal_sensor(entry.unique_id)
            ):
                _LOGGER.debug(
                    "Removing legacy cellular signal sensor %s (firmware 4.9+)",
                    entry.unique_id,
                )
                entity_registry.async_remove(entry.entity_id)
                removed = True

            if not removed:
                mac = self._extract_mac_from_entry(entry)

                if mac:
                    dev_reg = dr.async_get(self.hass)
                    devices = dev_reg.async_get_devices(
                        connections={(CONNECTION_NETWORK_MAC, format_mac(mac))}
                    )
                    device = next(
                        (d for d in devices if d.config_entry_id == self._entry.entry_id),
                        None,
                    )
                    if not device or not any(
                        d.config_entry_id != self._entry.entry_id for d in devices
                    ):
                        if not self._unknown_device_allowed(mac):
                            _LOGGER.debug(
                                "Removing unknown device entity %s (discovery disabled)",
                                entry.entity_id,
                            )
                            entity_registry.async_remove(entry.entity_id)
                            if device:
                                _LOGGER.debug(
                                    "Removing unknown device %s (discovery disabled)",
                                    device.name or mac,
                                )
                                dev_reg.async_remove_device(device.id)
                            removed = True

            if removed:
                continue

            if entry.domain == TRACKER_DOMAIN:
                self._devices[entry.unique_id] = ClientDeviceInfo(
                    entry.unique_id,
                    entry.original_name,
                )
        await self.fetch_all_data()
        self._register_periodic_cleanup()
        await self._async_cleanup_orphaned_sensor_entities()

    def _register_periodic_cleanup(self) -> None:
        on_unload = getattr(self._entry, "async_on_unload", None)
        if on_unload is None:
            return
        on_unload(
            async_track_time_interval(
                self.hass,
                self._periodic_cleanup_callback,
                timedelta(minutes=30),
            )
        )

    async def _periodic_cleanup_callback(self, _now: datetime) -> None:
        try:
            await self._async_cleanup_orphaned_sensor_entities()
        except (APIClientError, ClientError, TimeoutError, OSError):
            _LOGGER.debug(
                "Periodic entity cleanup deferred: hub state unavailable",
                exc_info=True,
            )

    def _create_api_client(self) -> GLinetApiClient:
        session = async_get_clientsession(self.hass)
        verify_ssl = self._settings.get(CONF_VERIFY_SSL, False)
        return GLinetApiClient(
            base_url=f"{self._host}{API_PATH}", session=session, verify_ssl=verify_ssl
        )

    async def _async_load_router_info(self) -> None:
        try:
            self._api = self._create_api_client()
            await self._api.authenticate(
                self._settings.get(CONF_USERNAME, DEFAULT_USERNAME),
                self._settings[CONF_PASSWORD],
            )
            router_info = await self._invoke_api(self._api.system.get_info)
        except (ClientError, TimeoutError, OSError) as exc:
            _LOGGER.exception("Error connecting to GL.iNet router %s", self._host)
            raise ConfigEntryNotReady from exc
        except AuthenticationError as exc:
            raise ConfigEntryAuthFailed from exc

        if not router_info:
            raise ConfigEntryNotReady("Unable to retrieve router info during setup")

        self._model = str(router_info.model or "UNKNOWN")
        self._sw_version = str(router_info.firmware_version or "UNKNOWN")
        self._factory_mac = str(router_info.mac or "UNKNOWN")
        self._late_init_complete = True

    async def refresh_session_token(self) -> None:
        api = self.router_api
        attempts = 3
        for attempt in range(attempts):
            try:
                await api.authenticate(
                    self._settings.get(CONF_USERNAME, DEFAULT_USERNAME),
                    self._settings[CONF_PASSWORD],
                )
                _LOGGER.debug("GL.iNet router %s token was renewed", self._host)
                return
            except (AuthenticationError, TokenError, NonZeroResponse) as exc:
                if attempt < attempts - 1:
                    _LOGGER.debug(
                        "Attempt %d/%d: GL.iNet router %s failed to renew token: %s. Retrying...",
                        attempt + 1,
                        attempts,
                        self._host,
                        exc,
                    )
                    continue
                _LOGGER.error(
                    "GL.iNet router %s failed to renew the token after %d attempts: %s.",
                    self._host,
                    attempts,
                    exc,
                )
                raise ConfigEntryAuthFailed from exc

    async def fetch_all_data(self, _: datetime | None = None) -> None:
        try:
            await self.refresh_session_token()
        except ConfigEntryAuthFailed:
            raise
        except (APIClientError, ClientError, TimeoutError, OSError):
            _LOGGER.debug(
                "Proactive token refresh failed for %s; will retry during API calls",
                self._host,
            )

        tasks: list[Awaitable[Any]] = [
            self.fetch_system_status(),
            self.fetch_kmwan_status(),
            self.fetch_connected_devices(),
            self.fetch_wifi_interfaces(),
            self.fetch_fan_status(),
            self.fetch_led_status(),
        ]
        now = utcnow()
        run_upgrade_check = False
        last_upgrade_check = getattr(self, "_last_upgrade_check", None)
        if last_upgrade_check is None:
            run_upgrade_check = True
        else:
            try:
                if (now - last_upgrade_check).total_seconds() >= 86400:
                    run_upgrade_check = True
            except (TypeError, AttributeError):
                run_upgrade_check = True
        if run_upgrade_check:
            tasks.insert(2, self.fetch_upgrade_info())

        if self.feature_enabled(FEATURE_WG_CLIENT):
            tasks.append(self.fetch_wireguard_clients())
        else:
            self._wireguard_clients = {}
            self._wireguard_connections = None

        if self.feature_enabled(FEATURE_WG_SERVER):
            tasks.append(self.fetch_wg_server_status())
        else:
            self._wg_server_status = {}
            self._wg_server_peers = []

        if self.feature_enabled(FEATURE_OVPN_CLIENT):
            tasks.append(self.fetch_ovpn_clients())
        else:
            self._ovpn_clients = {}
            self._ovpn_connections = None

        if self.feature_enabled(FEATURE_WG_CLIENT) or self.feature_enabled(FEATURE_OVPN_CLIENT):
            tasks.append(self.fetch_vpn_tunnels())
        else:
            self._vpn_tunnels = {}
            self._vpn_tunnel_connections = None

        if self.feature_enabled(FEATURE_OVPN_SERVER):
            tasks.append(self.fetch_ovpn_server_status())
        else:
            self._ovpn_server_status = {}
            self._ovpn_server_users = []

        if self.feature_enabled(FEATURE_TAILSCALE):
            tasks.append(self.fetch_tailscale_state())
        else:
            self._tailscale_config = {}
            self._tailscale_connection = None

        if self.feature_enabled(FEATURE_ZEROTIER):
            tasks.append(self.fetch_zerotier_status())
        else:
            self._zerotier_status = None

        if self.feature_enabled(FEATURE_CELLULAR):
            tasks.append(self.fetch_cellular_status())
        else:
            self._cellular_status = {}
            self._modems = {}
            self._cached_modem_info = None
            self._default_modem_bus = None
            self._default_modem_slot = None
            self._traffic_sim_data = {}
            self._traffic_config_save_to_flash = None
            self._entity_cleanup_rules = []

        if self.feature_enabled(FEATURE_REPEATER):
            tasks.extend(
                [
                    self.fetch_repeater_status(),
                    self.fetch_repeater_config(),
                    self.fetch_saved_networks(),
                ]
            )
        else:
            self._repeater_status = None
            self._repeater_config = {}
            self._scanned_networks = []
            self._saved_networks = []
            self._last_wifi_scan = None

        if self.feature_enabled(FEATURE_ADGUARD):
            tasks.append(self.fetch_adguard_status())
        else:
            self._adguard_status = None

        if self.feature_enabled(FEATURE_FIREWALL):
            tasks.extend(
                [
                    self.fetch_firewall_rules(),
                    self.fetch_dmz_config(),
                    self.fetch_port_forwards(),
                    self.fetch_wan_access(),
                    self.fetch_zone_list(),
                ]
            )
        else:
            self._firewall_rules = []
            self._dmz_config = {}
            self._port_forwards = []
            self._wan_access = {}
            self._zone_list = {}

        if self.feature_enabled(FEATURE_PARENTAL_CONTROL):
            tasks.extend(
                [
                    self.fetch_parental_control_status(),
                    self.fetch_access_control_config(),
                ]
            )
        else:
            self._parental_status = ParentalStatus()
            self._access_control_config = {}
            self._access_control_mode = "black"
            self._black_mac = []
            self._white_mac = []

        if self.parallel_requests:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    _LOGGER.debug(
                        "Parallel fetch raised: %s",
                        result,
                        exc_info=result,
                    )
        else:
            for task in tasks:
                await task

        if run_upgrade_check:
            self._last_upgrade_check = utcnow()

        if self.feature_enabled(FEATURE_SMS):
            await self.fetch_sms_messages()
        else:
            self._sms_messages = {}

    async def _async_poll_update(self, _: datetime | None = None) -> None:
        await self.async_refresh()

    async def _invoke_api(self, api_callable: Callable[[], Awaitable[T]]) -> T | None:
        try:
            if self._token_error or self._connect_error:
                await self.refresh_session_token()
            response = await api_callable()
        except TimeoutError:
            if not self._connect_error:
                _LOGGER.exception("GL.iNet router %s did not respond in time", self._host)
            self._connect_error = True
            return None
        except (TokenError, AuthenticationError):
            if not self._connect_error:
                _LOGGER.warning(
                    "GL.iNet router %s rejected the token or access was denied; "
                    "a reauthentication will be attempted",
                    self._host,
                )
            self._connect_error = True
            self._token_error = True
            return None
        except NonZeroResponse:
            if not self._connect_error:
                _LOGGER.exception("GL.iNet router %s returned a router error response", self._host)
            self._connect_error = True
            return None
        except ConfigEntryAuthFailed:
            raise
        except Exception:
            if not self._connect_error:
                _LOGGER.exception("GL.iNet router %s returned an unexpected error", self._host)
            self._connect_error = True
            return None

        if self._token_error:
            self._token_error = False
            _LOGGER.info("GL.iNet router %s token is valid again", self._host)
        if self._connect_error:
            self._connect_error = False
            _LOGGER.info("Reconnected to GL.iNet router %s", self._host)
        return response

    async def _invoke_optional_api(self, api_callable: Callable[[], Awaitable[T]]) -> T | None:
        try:
            return await api_callable()
        except (TokenError, AuthenticationError):
            self._token_error = True
            return None
        except (APIClientError, OSError, TimeoutError, ValueError, NonZeroResponse):
            _LOGGER.debug("Optional GL.iNet router API is unavailable", exc_info=True)
            return None

    async def reboot(self, delay: int = 0) -> None:
        await self._invoke_api(lambda: self.router_api.system.reboot(delay))

    async def fetch_system_status(self) -> None:
        response = await self._invoke_api(self.router_api.system.get_status)
        if response:
            self._system_status = response

    async def fetch_kmwan_status(self) -> None:
        response = await self._invoke_optional_api(self.router_api.system.get_kmwan_status)
        self._kmwan_status = response or {}

    async def get_mwan3_config(self) -> dict[str, Any]:
        response = await self._invoke_optional_api(self.router_api.mwan3.get_config)
        return response or {}

    async def get_mwan3_status(self) -> dict[str, Any]:
        response = await self._invoke_optional_api(self.router_api.mwan3.get_status)
        return response or {}

    async def set_mwan3_config(self, config: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.mwan3.set_config(config))
        await self.fetch_kmwan_status()

    async def set_mwan3_interface(self, interface: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.mwan3.set_interface(interface))
        await self.fetch_kmwan_status()

    async def get_kmwan_config(self) -> dict[str, Any]:
        response = await self._invoke_optional_api(self.router_api.kmwan.get_config)
        return response or {}

    async def get_kmwan_status(self) -> dict[str, Any]:
        response = await self._invoke_optional_api(self.router_api.kmwan.get_status)
        return response or {}

    async def set_kmwan_config(self, config: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.kmwan.set_config(config))
        await self.fetch_kmwan_status()

    async def set_kmwan_interface(self, interface: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.kmwan.set_interface(interface))
        await self.fetch_kmwan_status()

    async def set_kmwan_sensitivity(self, sensitivity: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.kmwan.set_sensitivity(sensitivity))
        await self.fetch_kmwan_status()

    async def fetch_upgrade_info(self) -> None:
        if getattr(self, "_api", None) is None:
            self._upgrade_info = {}
            self._upgrade_config = {}
            self._upgrade_status = {}
            return
        info = await self._invoke_optional_api(self.router_api.upgrade.check_firmware_online)
        config = await self._invoke_optional_api(self.router_api.upgrade.get_config)
        status = await self._invoke_optional_api(self.router_api.upgrade.get_online_upgrade_status)
        self._upgrade_info = info or {}
        self._upgrade_config = config or {}
        self._upgrade_status = status or {}

    async def upgrade_firmware(self, keep_config: bool, keep_package: bool) -> None:
        params: dict[str, Any] = {
            "keep_config": keep_config,
            "keep_package": keep_package,
        }
        for key, aliases in _FIRMWARE_INFO_ALIASES.items():
            value = pick_first(self._upgrade_info, aliases)
            if value is not None:
                params[key] = value
        if "url" not in params or "id" not in params:
            raise ValueError("Firmware download URL is unavailable")
        await self._invoke_api(lambda: self.router_api.upgrade.upgrade_online(params))
        await self.fetch_upgrade_info()

    async def fetch_firewall_rules(self) -> None:
        response = await self._invoke_optional_api(self.router_api.firewall.get_rule_list)
        self._firewall_rules = (response or {}).get("res") or []

    async def fetch_dmz_config(self) -> None:
        response = await self._invoke_optional_api(self.router_api.firewall.get_dmz)
        self._dmz_config = response or {}

    async def fetch_port_forwards(self) -> None:
        response = await self._invoke_optional_api(self.router_api.firewall.get_port_forward_list)
        self._port_forwards = (response or {}).get("res") or []

    async def fetch_wan_access(self) -> None:
        response = await self._invoke_optional_api(self.router_api.firewall.get_wan_access)
        self._wan_access = response or {}

    async def fetch_zone_list(self) -> None:
        response = await self._invoke_optional_api(self.router_api.firewall.get_zone_list)
        self._zone_list = response or {}

    async def add_firewall_rule(self, params: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.firewall.add_rule(params))
        await self.fetch_firewall_rules()

    async def remove_firewall_rule(self, rule_id: str) -> None:
        params = {"id": rule_id}
        await self._invoke_api(lambda: self.router_api.firewall.remove_rule(params))
        await self.fetch_firewall_rules()

    async def get_firewall_rule_summaries(self) -> list[dict[str, str | None]]:
        await self.fetch_firewall_rules()
        return [
            {
                "id": str(rule.get("id")) if rule.get("id") is not None else None,
                "name": str(rule.get("name")) if rule.get("name") is not None else None,
            }
            for rule in self._firewall_rules
        ]

    async def add_port_forward(self, params: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.firewall.add_port_forward(params))
        await self.fetch_port_forwards()

    async def remove_port_forward(
        self,
        rule_id: str | None = None,
        remove_all: bool = False,
    ) -> None:
        params: dict[str, Any] = {}
        if remove_all:
            params["all"] = True
        elif rule_id:
            params["id"] = rule_id
        await self._invoke_api(lambda: self.router_api.firewall.remove_port_forward(params))
        await self.fetch_port_forwards()

    async def set_dmz_config(self, enabled: bool, dest_ip: str | None = None) -> None:
        await self._invoke_api(lambda: self.router_api.firewall.set_dmz(enabled, dest_ip))
        await self.fetch_dmz_config()

    async def set_wan_access(self, config: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.firewall.set_wan_access(config))
        await self.fetch_wan_access()

    async def get_mcu_battery_config(self) -> dict[str, Any]:
        response = await self._invoke_optional_api(self.router_api.mcu.get_battery_config)
        self._mcu_battery_config = response or {}
        return self._mcu_battery_config

    async def set_mcu_battery_config(self, config: dict[str, Any]) -> None:
        await self._invoke_api(lambda: self.router_api.mcu.set_battery_config(config))
        await self.get_mcu_battery_config()

    async def get_mcu_oled_config(self) -> dict[str, Any]:
        response = await self._invoke_optional_api(self.router_api.mcu.get_oled_config)
        self._mcu_oled_config = response or {}
        return self._mcu_oled_config

    async def set_mcu_oled_config(self, screen_display: dict[str, Any]) -> None:
        current = await self.get_mcu_oled_config()
        current_display = current.get("screen_display")
        if not isinstance(current_display, dict):
            current_display = {}
        config = {"screen_display": current_display | screen_display}
        await self._invoke_api(lambda: self.router_api.mcu.set_oled_config(config))
        await self.get_mcu_oled_config()

    async def fetch_access_control_config(self) -> None:
        response = await self._invoke_optional_api(self.router_api.black_white_list.get_config)
        self._access_control_config = response or {}
        self._access_control_mode = str(
            self._access_control_config.get("mode")
            or self._access_control_config.get("type")
            or "black"
        )
        self._black_mac = _extract_access_macs(
            self._access_control_config,
            "black",
            "black_mac",
        )
        self._white_mac = _extract_access_macs(
            self._access_control_config,
            "white",
            "white_mac",
        )

    async def fetch_parental_control_status(self) -> None:
        config = await self._invoke_optional_api(self.router_api.parental_control.get_config)
        status = await self._invoke_optional_api(self.router_api.parental_control.get_status)
        mode = await self._invoke_optional_api(self.router_api.parental_control.get_mode)
        self._parental_status = ParentalStatus.from_api_response(config, status, mode)

    async def set_parental_control_enabled(self, enabled: bool) -> None:
        await self._invoke_api(lambda: self.router_api.parental_control.set_config(enabled))
        await self.fetch_parental_control_status()

    async def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        group = self._parental_status.groups.get(group_id)
        params = group.with_updates(enable=enabled, enabled=enabled) if group else {}
        params.pop("id", None)
        await self._invoke_api(
            lambda: self.router_api.parental_control.set_group(group_id, **params)
        )
        await self.fetch_parental_control_status()

    async def set_temporary_override(
        self,
        group_id: str,
        enable: bool,
        duration: str,
        rule_id: str,
    ) -> None:
        await self._invoke_api(
            lambda: self.router_api.parental_control.set_brief(
                enable=enable,
                time=duration,
                rule_id=rule_id,
                group_id=group_id,
                manual_stop=False,
            )
        )
        await self.fetch_parental_control_status()

    async def set_parental_mode(self, mode: int) -> None:
        await self._invoke_api(lambda: self.router_api.parental_control.set_mode(mode))
        await self.fetch_parental_control_status()

    async def update_parental_signatures(self) -> None:
        await self._invoke_api(self.router_api.parental_control.update)

    async def set_access_control_mode(self, mode: str) -> None:
        macs = self._white_mac if mode == "white" else self._black_mac
        await self._invoke_api(lambda: self.router_api.black_white_list.set_config(mode, macs))
        await self.fetch_access_control_config()

    async def set_single_device_block(self, mac: str, block: bool) -> None:
        mode = self._access_control_mode
        is_black = _resolve_access_mode(mode) == "black"
        operate = "add" if (block if is_black else not block) else "del"
        await self._invoke_api(
            lambda: self.router_api.black_white_list.set_single_mac(
                mode,
                operate,
                mac.lower(),
            )
        )
        await self.fetch_access_control_config()

    async def set_group_schedules_enabled(self, group_id: str, enabled: bool) -> None:
        group = self._parental_status.groups.get(group_id)
        params = (
            group.with_updates(schedule_enable=enabled, schedules_enabled=enabled) if group else {}
        )
        params.pop("id", None)
        await self._invoke_api(
            lambda: self.router_api.parental_control.set_group(group_id, **params)
        )
        await self.fetch_parental_control_status()

    async def assign_device_to_parental_group(
        self,
        mac: str,
        group_name_or_id: str | None,
    ) -> None:
        normalized_mac = mac.lower()
        target = self.parental_group_by_name_or_id(group_name_or_id)
        for group in self.parental_groups.values():
            group_macs = [item.lower() for item in group.macs]
            should_include = target is not None and group.id == target.id
            if should_include and normalized_mac not in group_macs:
                group_macs.append(normalized_mac)
            if not should_include and normalized_mac in group_macs:
                group_macs = [item for item in group_macs if item != normalized_mac]
            if group_macs != group.macs:
                params: dict[str, Any] = group.with_updates(mac=group_macs, macs=group_macs)
                params.pop("id", None)
                await self._invoke_api(
                    lambda group=group, params=params: self.router_api.parental_control.set_group(  # type: ignore[misc]
                        group.id,
                        **params,
                    )
                )
        await self.fetch_parental_control_status()

    async def fetch_connected_devices(self) -> None:
        new_device = False
        connected_devices = await self._invoke_api(self.router_api.clients.get_online)
        if connected_devices is None:
            return

        self._all_connected_clients = connected_devices

        consider_home = self._options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds())
        for device_mac, device in self._devices.items():
            device.apply_update(connected_devices.get(device_mac), consider_home)

        dev_reg = dr.async_get(self.hass)
        for device_mac, dev_info in connected_devices.items():
            if device_mac in self._devices:
                continue

            existing_device = dev_reg.async_get_device_by_connection(
                (CONNECTION_NETWORK_MAC, format_mac(device_mac)),
                self._entry.entry_id,
            )

            if not existing_device:
                if not self._unknown_device_allowed(device_mac):
                    continue
                device_is_known = False
            else:
                device_is_known = True

            new_device = True
            device = ClientDeviceInfo(device_mac)
            device.is_known = device_is_known
            device.apply_update(dev_info)
            self._devices[device_mac] = device

        async_dispatcher_send(self.hass, self.event_device_updated)
        if new_device:
            async_dispatcher_send(self.hass, self.event_device_added)

        await self._async_cleanup_stale_devices()

    async def _async_cleanup_stale_devices(self) -> None:
        cleanup_minutes = self._settings.get(CONF_CLEANUP_DEVICES, 0)
        if cleanup_minutes <= 0:
            return

        now = utcnow()
        stale_limit = timedelta(minutes=cleanup_minutes)
        to_remove = []

        for mac, device in self._devices.items():
            if not device.is_connected and (now - device.last_activity) > stale_limit:
                to_remove.append(mac)

        if not to_remove:
            return

        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)

        for mac in to_remove:
            _LOGGER.debug("Cleaning up stale discovered device %s", mac)
            device = self._devices.pop(mac)
            entities = er.async_entries_for_config_entry(entity_registry, self._entry.entry_id)
            for entry in entities:
                if (
                    entry.unique_id == mac
                    or entry.unique_id.startswith(f"glinet_client_sensor/{mac}/")
                    or entry.unique_id
                    in {
                        f"glinet_switch/{mac}/internet_access",
                        f"glinet_select/{mac}/parental_control_group",
                    }
                ):
                    entity_registry.async_remove(entry.entity_id)
            ha_device = device_registry.async_get_device_by_connection(
                (CONNECTION_NETWORK_MAC, format_mac(mac)),
                self._entry.entry_id,
            )
            if ha_device:
                device_registry.async_remove_device(ha_device.id)

    async def fetch_wifi_interfaces(self) -> None:
        response = await self._invoke_api(self.router_api.wifi.get_interfaces)
        if not response:
            return
        for name, iface in response.items():
            self._wifi_ifaces[name] = WifiInterface(
                name=name,
                enabled=iface.enabled,
                ssid=iface.ssid,
                guest=iface.guest,
                hidden=iface.hidden,
                encryption=iface.encryption or "UNKNOWN",
            )

    async def set_wifi_interface_enabled(self, iface_name: str, enabled: bool) -> None:
        await self._invoke_api(
            lambda: self.router_api.wifi.set_interface_enabled(iface_name, enabled)
        )
        await self.fetch_wifi_interfaces()

    async def fetch_wireguard_clients(self) -> None:
        response = await self._invoke_api(self.router_api.wg_client.get_wireguard_clients)
        if response is None:
            return

        self._wireguard_clients = {
            int(config["peer_id"]): WireGuardClient(
                name=str(config["name"]),
                connected=False,
                group_id=int(config["group_id"]),
                peer_id=int(config["peer_id"]),
                tunnel_id=(
                    int(config["tunnel_id"]) if config.get("tunnel_id") is not None else None
                ),
            )
            for config in response
        }
        if not self._wireguard_clients:
            self._wireguard_connections = []
            return

        state_response = await self._invoke_api(self.router_api.wg_client.get_wireguard_state)
        if state_response is None:
            return

        self._wireguard_connections = []
        for config in state_response:
            if config.get("type") not in {None, "wireguard"}:
                continue
            peer_id = config.get("peer_id")
            if peer_id not in self._wireguard_clients:
                continue
            client = self._wireguard_clients[peer_id]
            client.tunnel_id = config.get("tunnel_id", client.tunnel_id)
            client.connected = config.get("status", 0) != 0 or bool(config.get("enabled", False))
            if client.connected:
                self._wireguard_connections.append(client)

    async def start_vpn_client(self, group_id: int, peer_id: int) -> None:
        await self._invoke_api(
            lambda: self.router_api.wg_client.start_wireguard_client(group_id, peer_id)
        )
        await self.fetch_wireguard_clients()

    async def stop_vpn_client(self, group_id: int, peer_id: int) -> None:
        await self._invoke_api(
            lambda: self.router_api.wg_client.stop_wireguard_client(group_id, peer_id)
        )
        await self.fetch_wireguard_clients()

    def _dashboard_vpn_client(self) -> Any | None:
        api = getattr(self, "_api", None)
        if api is None:
            return None
        wg_client = getattr(api, "wg_client", None)
        if wg_client is None:
            return None
        return getattr(wg_client, "vpn_client", None)

    async def _is_dashboard_supported(self) -> bool:
        api = getattr(self, "_api", None)
        if api is None or self._dashboard_vpn_client() is None:
            return False
        try:
            return await api._is_firmware_at_least((4, 9, 0, 0))
        except (APIClientError, OSError, ValueError):
            return False

    async def fetch_vpn_tunnels(self) -> None:
        vpn_client = self._dashboard_vpn_client()
        if not await self._is_dashboard_supported() or vpn_client is None:
            self._vpn_tunnels = {}
            self._vpn_tunnel_connections = []
            return

        tunnel_response = await self._invoke_optional_api(vpn_client.get_tunnel)
        if not tunnel_response:
            self._vpn_tunnels = {}
            self._vpn_tunnel_connections = []
            return

        tunnels: dict[int, VpnTunnel] = {}
        defaults = tunnel_response.get("default_tunnels") or []
        user_tunnels = tunnel_response.get("tunnels") or []

        for raw in defaults:
            if not isinstance(raw, dict):
                continue
            try:
                tunnel = VpnTunnel.from_api_response(raw, is_default=True)
            except (TypeError, ValueError):
                continue
            if tunnel.tunnel_id:
                tunnels[tunnel.tunnel_id] = tunnel

        for raw in user_tunnels:
            if not isinstance(raw, dict):
                continue
            try:
                tunnel = VpnTunnel.from_api_response(raw, is_default=False)
            except (TypeError, ValueError):
                continue
            if tunnel.tunnel_id:
                tunnels[tunnel.tunnel_id] = tunnel

        self._vpn_tunnels = tunnels

        status_response = await self._invoke_optional_api(vpn_client.get_status)
        active_ids: set[int] = set()
        if isinstance(status_response, dict):
            for item in status_response.get("status_list") or []:
                if not isinstance(item, dict):
                    continue
                tid = item.get("tunnel_id")
                if tid is None:
                    continue
                if int(item.get("status", 0)) == 1 or bool(item.get("enabled", False)):
                    active_ids.add(int(tid))
        elif isinstance(status_response, list):
            for item in status_response:
                if not isinstance(item, dict):
                    continue
                tid = item.get("tunnel_id")
                if tid is None:
                    continue
                if int(item.get("status", 0)) == 1 or bool(item.get("enabled", False)):
                    active_ids.add(int(tid))

        connections: list[VpnTunnel] = []
        for tunnel_id, tunnel in tunnels.items():
            tunnel.connected = tunnel_id in active_ids
            if tunnel.connected:
                connections.append(tunnel)

        self._vpn_tunnel_connections = connections

        try:
            async_dispatcher_send(self.hass, self.event_vpn_tunnels_updated, set(tunnels.keys()))
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            _LOGGER.debug("Failed to dispatch vpn tunnels updated event", exc_info=True)

    async def set_vpn_tunnel(self, tunnel_id: int, enabled: bool) -> None:
        vpn_client = self._dashboard_vpn_client()
        if vpn_client is None:
            raise RuntimeError("VPN dashboard is not available on this firmware")
        await self._invoke_api(
            lambda: vpn_client.set_tunnel(
                tunnel_id=int(tunnel_id),
                enabled=bool(enabled),
            )
        )
        await self.fetch_vpn_tunnels()
        if self.feature_enabled(FEATURE_WG_CLIENT):
            await self.fetch_wireguard_clients()
        if self.feature_enabled(FEATURE_OVPN_CLIENT):
            await self.fetch_ovpn_clients()

    async def fetch_wg_server_status(self) -> None:
        response = await self._invoke_api(self.router_api.wg_server.get_status)
        if response is None:
            self._wg_server_status = {}
            return
        self._wg_server_status = response
        self._wg_server_peers = response.get("peers") or []

    async def start_wg_server(self) -> None:
        await self._invoke_api(self.router_api.wg_server.start)
        await self.fetch_wg_server_status()

    async def stop_wg_server(self) -> None:
        await self._invoke_api(self.router_api.wg_server.stop)
        await self.fetch_wg_server_status()

    async def fetch_ovpn_clients(self) -> None:
        response = await self._invoke_api(self.router_api.ovpn_client.get_ovpn_clients)
        if response is None:
            return

        self._ovpn_clients = {}
        self._ovpn_raw_clients = {}
        for config in response:
            key = f"{config['group_id']}_{config['client_id']}"
            locations = []
            if config.get("location"):
                locations = [loc.strip() for loc in config["location"].split(";")]

            remotes = []
            remote_val = config.get("remote")
            if isinstance(remote_val, list):
                remotes = remote_val
            elif isinstance(remote_val, str):
                remotes = [remote_val]

            self._ovpn_clients[key] = OpenVpnClient(
                name=str(config["name"]),
                connected=False,
                group_id=int(config["group_id"]),
                client_id=int(config["client_id"]),
                group_name=config.get("group_name"),
                location=config.get("location"),
                locations=locations,
                remotes=remotes,
                tunnel_id=config.get("tunnel_id"),
            )
            self._ovpn_raw_clients[key] = config["raw_data"]

        if not self._ovpn_clients:
            self._ovpn_connections = []
            return

        state_response = await self._invoke_api(self.router_api.ovpn_client.get_status)
        if state_response is None:
            self._ovpn_client_status = {}
            return

        self._ovpn_client_status = state_response  # type: ignore[assignment]
        self._ovpn_connections = []
        for state in state_response:
            if state.get("type") not in {None, "openvpn"}:
                continue
            status = state.get("status", 0)
            if status == 1:
                gid = state.get("group_id")
                cid = state.get("client_id")
                key = f"{gid}_{cid}"
                if key in self._ovpn_clients:
                    client = self._ovpn_clients[key]
                    client.connected = True
                    client.tunnel_id = state.get("tunnel_id", client.tunnel_id)
                    self._ovpn_connections.append(client)

    @property
    def ovpn_client_status(self) -> dict[str, Any]:
        return self._ovpn_client_status

    async def start_ovpn_client(self, group_id: int, client_id: int) -> None:
        await self.stop_all_ovpns()

        key = f"{group_id}_{client_id}"
        client = self._ovpn_clients.get(key)
        tunnel_id = client.tunnel_id if client else None

        await self._invoke_api(
            lambda: self.router_api.ovpn_client.start(group_id, client_id, tunnel_id)
        )
        await self.fetch_ovpn_clients()

    async def stop_ovpn_client(
        self, group_id: int, client_id: int, tunnel_id: int | None = None
    ) -> None:
        await self._invoke_api(
            lambda: self.router_api.ovpn_client.stop(group_id, client_id, tunnel_id)
        )
        await self.fetch_ovpn_clients()

    async def stop_all_ovpns(self) -> None:
        if not self._ovpn_connections:
            return
        for conn in self._ovpn_connections:
            await self._invoke_api(
                lambda conn=conn: self.router_api.ovpn_client.stop(  # type: ignore[misc]
                    conn.group_id, conn.client_id, conn.tunnel_id
                )
            )
        await self.fetch_ovpn_clients()

    async def fetch_ovpn_server_status(self) -> None:
        status_response = await self._invoke_api(self.router_api.ovpn_server.get_status)
        if status_response is None:
            self._ovpn_server_status = {}
            return
        self._ovpn_server_status = status_response

        users_response = await self._invoke_api(self.router_api.ovpn_server.get_user_list)
        self._ovpn_server_users = users_response or []

    async def start_ovpn_server(self) -> None:
        await self._invoke_api(self.router_api.ovpn_server.start)
        await self.fetch_ovpn_server_status()

    async def stop_ovpn_server(self) -> None:
        await self._invoke_api(self.router_api.ovpn_server.stop)
        await self.fetch_ovpn_server_status()

    async def fetch_tailscale_state(self) -> None:
        details = await self._invoke_optional_api(self.router_api.tailscale.get_details)
        if not details:
            self._tailscale_config = {}
            self._tailscale_connection = None
            return

        self._tailscale_config = details["config"]
        self._tailscale_connection = details["connection"] == TailscaleConnection.CONNECTED

    async def connect_tailscale(self) -> None:
        await self._invoke_api(self.router_api.tailscale.connect)
        await self.fetch_tailscale_state()

    async def disconnect_tailscale(self) -> None:
        await self._invoke_api(self.router_api.tailscale.disconnect)
        await self.fetch_tailscale_state()

    @property
    def zerotier_status(self) -> ZeroTierStatus | None:
        return self._zerotier_status

    async def fetch_zerotier_status(self) -> None:
        config = await self._invoke_optional_api(self.router_api.zerotier.get_config)
        status = await self._invoke_optional_api(self.router_api.zerotier.get_status)
        if config is None or status is None:
            self._zerotier_status = None
            return
        self._zerotier_status = ZeroTierStatus.from_api_response(config, status)

    async def start_zerotier(self) -> None:
        status = self._zerotier_status
        if status and status.network_id:
            await self._invoke_api(
                lambda: self.router_api.zerotier.set_config(
                    {"enabled": True, "id": status.network_id}
                )
            )
            await self.fetch_zerotier_status()

    async def stop_zerotier(self) -> None:
        status = self._zerotier_status
        if status and status.network_id:
            await self._invoke_api(
                lambda: self.router_api.zerotier.set_config(
                    {"enabled": False, "id": status.network_id}
                )
            )
            await self.fetch_zerotier_status()

    @property
    def led_enabled(self) -> bool | None:
        return self._led_enabled

    async def fetch_led_status(self) -> None:
        response = await self._invoke_optional_api(self.router_api.led.get_config)
        if response:
            self._led_enabled = response.get("led_enable")

    async def set_led_enabled(self, enabled: bool) -> None:
        await self._invoke_api(lambda: self.router_api.led.set_config({"led_enable": enabled}))
        await self.fetch_led_status()

    async def fetch_adguard_status(self) -> None:
        data = await self._invoke_optional_api(self.router_api.adguard.get_config)
        if data is not None:
            self._adguard_status = AdGuardStatus.from_api_response(data)

    @property
    def adguard_status(self) -> AdGuardStatus | None:
        return self._adguard_status

    async def set_adguard_enabled(self, enabled: bool) -> None:
        current = self._adguard_status
        dns_enabled = current.dns_enabled if current else False
        await self._invoke_api(lambda: self.router_api.adguard.set_config(enabled, dns_enabled))
        await self.fetch_adguard_status()

    async def set_adguard_dns_enabled(self, dns_enabled: bool) -> None:
        current = self._adguard_status
        enabled = current.enabled if current else False
        await self._invoke_api(lambda: self.router_api.adguard.set_config(enabled, dns_enabled))
        await self.fetch_adguard_status()

    async def fetch_cellular_status(self) -> None:
        if self._cached_modem_info is None:
            info_response = await self._invoke_optional_api(self.router_api.modem.get_info)
            self._cached_modem_info = dict(info_response or {})
        else:
            info_response = self._cached_modem_info

        status_response = await self._invoke_optional_api(self.router_api.modem.get_status)

        modems = _merge_modem_lists(
            dict(info_response or {}).get("modems", []),
            dict(status_response or {}).get("modems", []),
        )
        self._modems = {_modem_key(modem): modem for modem in modems if modem.get("bus")}

        if self.is_firmware_4_9_or_above and self._modems:
            await self._apply_49_sim_config_to_modems(self._modems)

        default_modem = _select_sms_modem(self._modems)
        self._default_modem_bus = str(default_modem.get("bus")) if default_modem else None
        self._default_modem_slot = default_modem.get("slot") if default_modem else None
        self._cellular_status = {
            "modems": modems,
            "default_bus": self._default_modem_bus,
            "default_slot": self._default_modem_slot,
        }

        await self.fetch_traffic_config()

    async def fetch_traffic_config(self) -> None:
        bus = self._traffic_config_bus()
        if not bus:
            self._traffic_sim_data = {}
            self._traffic_config_save_to_flash = None
            return

        response = await self._invoke_optional_api(
            lambda b=bus: self.router_api.modem.get_traffic_config(b)  # type: ignore[misc]
        )
        if not response:
            self._traffic_sim_data = {}
            self._traffic_config_save_to_flash = None
            return

        save_to_flash = bool(response.get("save_to_flash"))
        sims = _normalise_traffic_config(
            response,
            is_firmware_4_9=self.is_firmware_4_9_or_above,
        )
        self._traffic_sim_data = {sim["slot"]: sim for sim in sims}
        self._traffic_config_save_to_flash = save_to_flash
        self._refresh_cellular_limit_cleanup_rule()
        await self._async_cleanup_orphaned_sensor_entities()
        async_dispatcher_send(self.hass, self.event_cellular_traffic_config_updated)

    async def _async_cleanup_orphaned_sensor_entities(self) -> None:
        rules = getattr(self, "_entity_cleanup_rules", None) or []
        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(entity_registry, self._entry.entry_id)
        for rule in rules:
            for entry in entries:
                if not rule.matches(entry):
                    continue
                if rule.should_keep(entry):
                    continue
                _LOGGER.debug(
                    "Removing orphaned sensor %s (%s)",
                    entry.entity_id,
                    rule.description,
                )
                entity_registry.async_remove(entry.entity_id)

    def _refresh_cellular_limit_cleanup_rule(self) -> None:
        prefix = f"glinet_sensor/{self._factory_mac}/cellular_traffic_sim_"
        limit_keys = {"data_limit", "days_until_reset"}
        sim_data = self._traffic_sim_data

        def _matches(entry: RegistryEntry) -> bool:
            if not entry.unique_id.startswith(prefix):
                return False
            suffix = entry.unique_id[len(prefix) :]
            parts = suffix.split("_")
            if len(parts) < 4:
                return False
            return "_".join(parts[2:]) in limit_keys

        def _should_keep(entry: RegistryEntry) -> bool:
            suffix = entry.unique_id[len(prefix) :]
            parts = suffix.split("_")
            if len(parts) < 4:
                return True
            try:
                slot = int(parts[0])
            except (TypeError, ValueError):
                return True
            sim_type = parts[1]
            record = sim_data.get(slot)
            if not isinstance(record, dict):
                return True
            sim_type_record = record.get("sim_type")
            if sim_type_record is None or str(sim_type_record) != sim_type:
                return True
            return bool(record.get("limit_enabled"))

        self._entity_cleanup_rules = [
            rule
            for rule in self._entity_cleanup_rules
            if rule.description != "cellular traffic limit disabled"
        ]
        self._entity_cleanup_rules.append(
            EntityCleanupRule(
                description="cellular traffic limit disabled",
                matches=_matches,
                should_keep=_should_keep,
            )
        )

    def _traffic_config_bus(self) -> str | None:
        for modem in self._modems.values():
            bus = modem.get("bus")
            if bus:
                return str(bus)
        return self._default_modem_bus

    async def _apply_49_sim_config_to_modems(
        self,
        modems: dict[str, dict[str, Any]],
    ) -> None:
        if not modems:
            return
        seen_buses: set[str] = set()
        for modem in modems.values():
            bus = modem.get("bus")
            if not bus or bus in seen_buses:
                continue
            seen_buses.add(bus)
            sim_response = await self._invoke_optional_api(
                lambda b=bus: self.router_api.modem.get_sim_config(b)  # type: ignore[misc]
            )
            if not sim_response:
                continue
            self._merge_sim_config(modem, sim_response)

    def _merge_sim_config(
        self,
        modem: dict[str, Any],
        sim_response: dict[str, Any],
    ) -> None:
        if not isinstance(sim_response, dict):
            return
        modem_iccid = str(modem.get("iccid") or "")
        chosen: dict[str, Any] | None = None
        if modem_iccid and modem_iccid in sim_response:
            chosen = sim_response[modem_iccid]
        else:
            for value in sim_response.values():
                if isinstance(value, dict):
                    chosen = value
                    break
        if not isinstance(chosen, dict):
            return
        apn = chosen.get("apn")
        if not apn:
            return
        simcard = modem.get("simcard")
        if not isinstance(simcard, dict):
            simcard = {}
        simcard["apn"] = apn
        sim_fields = (
            "iccid",
            "username",
            "password",
            "pincode",
            "auth",
            "ip_type",
            "roaming",
            "cid",
        )
        for key in sim_fields:
            value = chosen.get(key)
            if value is not None and key not in simcard:
                simcard[key] = value
        modem["simcard"] = simcard

    async def fetch_repeater_status(self) -> None:
        response = await self._invoke_optional_api(self.router_api.repeater.get_status)
        if response is None:
            self._repeater_status = None
            return
        self._repeater_status = RepeaterStatus.from_api_response(response)

    async def fetch_repeater_config(self) -> None:
        response = await self._invoke_optional_api(self.router_api.repeater.get_config)
        if response is not None:
            self._repeater_config = response

    async def set_repeater_auto_switch(self, enabled: bool) -> None:
        await self._invoke_api(lambda: self.router_api.repeater.set_config({"auto": enabled}))
        await self.fetch_repeater_config()

    async def set_repeater_smart_reconnect(self, enabled: bool) -> None:
        await self._invoke_api(
            lambda: self.router_api.repeater.set_config({"smart_reconnect": enabled})
        )
        await self.fetch_repeater_config()

    async def set_repeater_bare_mode(self, enabled: bool) -> None:
        if enabled:
            await self._invoke_api(self.router_api.repeater.enter_bare_mode)
        else:
            await self._invoke_api(self.router_api.repeater.exit_bare_mode)
        await self.fetch_repeater_status()

    async def set_repeater_band(self, band: str | None) -> None:
        await self._invoke_api(lambda: self.router_api.repeater.set_config({"lock_band": band}))
        await self.fetch_repeater_config()

    async def fetch_fan_status(self) -> None:
        status = await self._invoke_optional_api(self.router_api.fan.get_status)
        if status is None:
            self._fan_status = None
            return
        config = await self._invoke_optional_api(self.router_api.fan.get_config)
        self._fan_status = FanStatus.from_api_response(status, config or {})

    async def set_fan_temperature(self, temperature: int) -> None:
        await self._invoke_api(lambda: self.router_api.fan.set_config(temperature))
        await self.fetch_fan_status()

    async def test_fan(self, duration: int = 10) -> None:
        await self._invoke_api(lambda: self.router_api.fan.set_test(test=True, time=duration))

    async def scan_wifi_networks(
        self,
        all_band: bool = False,
        dfs: bool = False,
        refresh: bool = False,
        store_results: bool = True,
    ) -> list[ScannedNetwork]:
        _LOGGER.info(
            "Starting WiFi network scan (all_band=%s, dfs=%s, refresh=%s)",
            all_band,
            dfs,
            refresh,
        )
        params: dict[str, Any] = {}
        if refresh or all_band or dfs:
            params["refresh"] = True
        response: list[dict[str, Any]] | None = await self._invoke_api(
            lambda: self.router_api.repeater.scan(params)
        )
        if response is None:
            _LOGGER.warning(
                "WiFi scan returned None, keeping %d cached networks",
                len(self._scanned_networks),
            )
            return self._scanned_networks
        networks = [ScannedNetwork.from_api_response(network) for network in response]
        _LOGGER.info("WiFi scan found %d networks", len(networks))
        if store_results:
            self._scanned_networks = networks
            self._last_wifi_scan = datetime.now()
            async_dispatcher_send(self.hass, self.event_networks_updated)
        return networks

    async def connect_to_wifi(
        self,
        ssid: str,
        password: str | None = None,
        remember: bool = True,
        bssid: str | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "ssid": ssid,
            "remember": remember,
            "manual": False,
            "protocol": "dhcp",
            "disguise": False,
            "auto_portal": False,
        }
        if password:
            params["key"] = password
        if bssid:
            params["bssid"] = bssid
        await self._invoke_api(lambda: self.router_api.repeater.connect(params))
        await self.fetch_repeater_status()

    async def disconnect_wifi(self) -> None:
        await self._invoke_api(self.router_api.repeater.disconnect)
        await self.fetch_repeater_status()

    async def fetch_saved_networks(self) -> None:
        response = await self._invoke_optional_api(self.router_api.repeater.get_saved_ap_list)
        if response is not None:
            self._saved_networks = response

    async def get_saved_wifi_networks(self) -> list[dict[str, Any]]:
        response = await self._invoke_api(self.router_api.repeater.get_saved_ap_list)
        return response or []

    async def remove_saved_wifi_network(self, ssid: str) -> None:
        await self._invoke_api(lambda: self.router_api.repeater.remove_saved_ap(ssid))
        await self.fetch_saved_networks()

    async def fetch_sms_messages(self) -> None:
        response = await self._invoke_optional_api(self.router_api.modem.get_sms_list)
        if response is None:
            return
        messages: dict[str, SmsMessage] = {}
        for index, item in enumerate(response):
            message_id = str(
                item.get("name")
                or item.get("id")
                or item.get("index")
                or item.get("message_id")
                or item.get("sn")
                or index
            )
            messages[message_id] = SmsMessage(
                message_id=message_id,
                phone_number=str(item.get("phone_number") or item.get("sender") or ""),
                text=str(item.get("body") or ""),
                bus=item.get("bus"),
                slot=item.get("slot"),
                status=get_first_int(item, ("status",)),
                timestamp=item.get("date") or item.get("time") or item.get("timestamp"),
                read=_sms_status_is_read(item.get("status")),
            )
        self._sms_messages = messages

    async def send_sms(self, recipient: str, text: str) -> None:
        bus = self._default_modem_bus
        slot = getattr(self, "_default_modem_slot", None)
        if bus is None:
            await self.fetch_cellular_status()
            bus = self._default_modem_bus
            slot = self._default_modem_slot
        if bus is None:
            raise RuntimeError("No SMS-capable GL.iNet modem was found")

        chunks = [text[i : i + 160] for i in range(0, len(text), 160)]
        for chunk in chunks:
            if slot is None:

                async def api_call(c: str = chunk):
                    return await self.router_api.modem.send_sms(bus, recipient, c)

            else:

                async def api_call(c: str = chunk):
                    return await self.router_api.modem.send_sms(bus, recipient, c, slot=slot)

            response = await self._invoke_optional_api(api_call)
            if response is None:
                raise RuntimeError("The router did not accept the SMS send request")

        await self.fetch_sms_messages()

    async def remove_sms(self, scope: int, message_id: str | None = None) -> None:
        message = self._sms_messages.get(message_id) if message_id else None
        bus = message.bus if message else self._default_modem_bus

        if bus is None:
            await self.fetch_cellular_status()
            bus = self._default_modem_bus
        if bus is None:
            raise RuntimeError("No GL.iNet modem bus is available for SMS removal")

        async def api_call():
            return await self.router_api.modem.remove_sms(bus, scope, message_id)

        await self._invoke_optional_api(api_call)
        if scope == 10 and message_id:
            self._sms_messages.pop(message_id, None)
        else:
            await self.fetch_sms_messages()

    def _get_unknown_devices_filter(self) -> set[str]:
        selected = self._settings.get(CONF_UNKNOWN_DEVICES_FILTER_SELECT, [])
        manual_raw = self._settings.get(CONF_UNKNOWN_DEVICES_FILTER_MANUAL, "")
        filter_set = set(selected)
        if manual_raw:
            for line in manual_raw.splitlines():
                mac = line.strip().lower()
                if mac:
                    filter_set.add(mac)
        return {mac.lower() for mac in filter_set}

    def _unknown_device_allowed(self, mac: str) -> bool:
        if not self._settings.get(CONF_ADD_ALL_DEVICES):
            return False
        filter_mode = self._settings.get(CONF_UNKNOWN_DEVICES_FILTER_MODE, "blacklist")
        filter_set = self._get_unknown_devices_filter()
        mac_lower = mac.lower()
        if filter_mode == "whitelist":
            return mac_lower in filter_set
        return mac_lower not in filter_set

    def apply_option_updates(self, new_options: dict[str, Any]) -> bool:
        self._options.update(new_options)
        self._settings = dict(self._entry.data) | new_options
        scan_seconds = int(self._settings.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        self.update_interval = timedelta(seconds=scan_seconds)
        return True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.router_id)},
            connections={
                (CONNECTION_NETWORK_MAC, format_mac(self.device_mac)),
                (CONNECTION_NETWORK_MAC, compute_mac_offset(self.device_mac, 1)),
            },
            name=self.hub_name,
            model=self.router_model or "GL.iNet Router",
            manufacturer="GL.iNet",
            configuration_url=self._host,
            sw_version=self._sw_version,
        )

    @property
    def router_api(self) -> GLinetApiClient:
        if self._api is None:
            raise RuntimeError("GL.iNet API client has not been initialized")
        return self._api

    async def custom_request(
        self, method: str, body: dict[str, Any] | list[Any] | None = None
    ) -> dict[str, Any] | list[Any] | None:
        return await self._invoke_api(lambda: self.router_api.custom_call(method, body))

    @property
    def router_host(self) -> str:
        return self._host

    @property
    def router_id(self) -> str:
        return self._entry.unique_id or self._entry.entry_id

    @property
    def router_device_id(self) -> str | None:
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device_by_identifier(
            (DOMAIN, self.router_id),
            self._entry.entry_id,
        )
        return device.id if device is not None else None

    @property
    def device_mac(self) -> str:
        return self._factory_mac

    @property
    def router_model(self) -> str:
        return self._model.upper()

    @property
    def hub_name(self) -> str:
        return f"GL.iNet {self._model.upper()}"

    @property
    def firmware_version(self) -> str:
        return self._sw_version

    @property
    def firmware_version_tuple(self) -> tuple[int, int, int, int] | None:
        version = (self._sw_version or "").strip()
        if not version or version == "UNKNOWN":
            return None
        try:
            return decode_firmware_version(version)
        except (TypeError, ValueError):
            return None

    @property
    def is_firmware_4_9_or_above(self) -> bool:
        version_tuple = self.firmware_version_tuple
        if version_tuple is not None:
            return version_tuple >= FIRMWARE_4_9
        api = getattr(self, "_api", None)
        cached = getattr(api, "_firmware_version", None) if api is not None else None
        return cached is not None and cached >= FIRMWARE_4_9

    @property
    def upgrade_info(self) -> dict[str, Any]:
        return self._upgrade_info

    @property
    def upgrade_config(self) -> dict[str, Any]:
        return self._upgrade_config

    @property
    def upgrade_status(self) -> dict[str, Any]:
        return self._upgrade_status

    @property
    def tracked_devices(self) -> dict[str, ClientDeviceInfo]:
        return self._devices

    @property
    def wifi_interfaces(self) -> dict[str, WifiInterface]:
        return self._wifi_ifaces

    @property
    def vpn_clients(self) -> dict[int, WireGuardClient]:
        return self._wireguard_clients

    @property
    def connected_vpn_clients(self) -> list[WireGuardClient] | None:
        return self._wireguard_connections

    @property
    def vpn_tunnels(self) -> dict[int, VpnTunnel]:
        return self._vpn_tunnels

    @property
    def connected_vpn_tunnels(self) -> list[VpnTunnel] | None:
        return self._vpn_tunnel_connections

    @property
    def wg_server_status(self) -> WireGuardServerStatus | None:
        if not self._wg_server_status:
            return None
        return WireGuardServerStatus.from_api_response(self._wg_server_status)

    @property
    def wg_server_connected_users(self) -> int:
        if not self._wg_server_peers:
            return 0
        return sum(1 for p in self._wg_server_peers if p.get("status") == 1)

    @property
    def ovpn_clients(self) -> dict[str, OpenVpnClient]:
        return self._ovpn_clients

    @property
    def connected_ovpn_clients(self) -> list[OpenVpnClient] | None:
        return self._ovpn_connections

    @property
    def ovpn_server_status(self) -> OpenVpnServerStatus | None:
        if not self._ovpn_server_status:
            return None
        return OpenVpnServerStatus.from_api_response(
            self._ovpn_server_status, self._ovpn_server_users
        )

    @property
    def ovpn_server_connected_users(self) -> int:
        return len(self._ovpn_server_users)

    @property
    def active_vpn_connections(self) -> list[VpnTunnel | WireGuardClient | OpenVpnClient]:
        connections: list[VpnTunnel | WireGuardClient | OpenVpnClient] = []
        if self._vpn_tunnel_connections:
            connections.extend(self._vpn_tunnel_connections)
        if self._wireguard_connections:
            connections.extend(self._wireguard_connections)
        if self._ovpn_connections:
            connections.extend(self._ovpn_connections)
        return connections

    @property
    def router_status(self) -> RouterStatus | None:
        return self._system_status

    @property
    def kmwan_status(self) -> dict[str, Any]:
        return self._kmwan_status

    @property
    def wan_status_monitors(self) -> set[str] | None:
        monitors = self._settings.get(CONF_WAN_STATUS_MONITORS)
        if monitors is None:
            return None
        return set(monitors)

    @property
    def cellular_status(self) -> dict[str, Any]:
        return self._cellular_status

    @property
    def traffic_sim_data(self) -> dict[int, dict[str, Any]]:
        return self._traffic_sim_data

    @property
    def traffic_config_save_to_flash(self) -> bool | None:
        return self._traffic_config_save_to_flash

    @property
    def online_client_count(self) -> int:
        return sum(1 for device in self._devices.values() if device.is_connected)

    @property
    def current_traffic_download(self) -> int:
        return sum(get_first_int(d, ("rx",)) or 0 for d in self._all_connected_clients.values())

    @property
    def current_traffic_upload(self) -> int:
        return sum(get_first_int(d, ("tx",)) or 0 for d in self._all_connected_clients.values())

    @property
    def total_traffic_download(self) -> int:
        return sum(
            get_first_int(d, ("total_rx",)) or 0 for d in self._all_connected_clients.values()
        )

    @property
    def total_traffic_upload(self) -> int:
        return sum(
            get_first_int(d, ("total_tx",)) or 0 for d in self._all_connected_clients.values()
        )

    @property
    def has_tailscale(self) -> bool:
        return bool(self._tailscale_config)

    @property
    def tailscale_settings(self) -> dict[str, Any]:
        return self._tailscale_config

    @property
    def tailscale_connected(self) -> bool | None:
        return self._tailscale_connection

    @property
    def has_zerotier(self) -> bool:
        return self._zerotier_status is not None

    @property
    def zerotier_connected(self) -> bool | None:
        if self._zerotier_status is None:
            return None
        return self._zerotier_status.connected

    @property
    def sms_messages(self) -> dict[str, SmsMessage]:
        return self._sms_messages

    @property
    def default_modem_bus(self) -> str | None:
        return self._default_modem_bus

    @property
    def access_control_mode(self) -> str:
        return self._access_control_mode

    @property
    def black_mac(self) -> list[str]:
        return self._black_mac

    @property
    def white_mac(self) -> list[str]:
        return self._white_mac

    @property
    def parental_status(self) -> ParentalStatus:
        return self._parental_status

    @property
    def parental_control_enabled(self) -> bool | None:
        return self._parental_status.enabled

    @property
    def parental_groups(self) -> dict[str, ParentalGroup]:
        return self._parental_status.groups

    def device_internet_access_enabled(self, mac: str) -> bool:
        normalized_mac = mac.lower()
        if _resolve_access_mode(self._access_control_mode) == "white":
            return normalized_mac in self._white_mac
        return normalized_mac not in self._black_mac

    def parental_group_for_device(self, mac: str) -> ParentalGroup | None:
        normalized_mac = mac.lower()
        for group in self._parental_status.groups.values():
            if normalized_mac in group.macs:
                return group
        return None

    def parental_group_by_name_or_id(self, value: str | None) -> ParentalGroup | None:
        if value is None:
            return None
        normalized_value = value.lower()
        for group in self._parental_status.groups.values():
            if group.id.lower() == normalized_value or group.name.lower() == normalized_value:
                return group
        return None

    @property
    def repeater_status(self) -> RepeaterStatus | None:
        return self._repeater_status

    @property
    def repeater_connected(self) -> bool | None:
        if self._repeater_status is None:
            return None
        return self._repeater_status.state in {
            RepeaterState.CONNECTED,
            RepeaterState.WAN_AVAILABLE,
        }

    @property
    def repeater_config(self) -> dict[str, Any]:
        return self._repeater_config

    @property
    def repeater_auto_switch(self) -> bool | None:
        return self._repeater_config.get("auto")

    @property
    def repeater_smart_reconnect(self) -> bool | None:
        return self._repeater_config.get("smart_reconnect")

    @property
    def repeater_bare_mode(self) -> bool | None:
        if self._repeater_status is None:
            return None
        return self._repeater_status.bare_mode

    @property
    def repeater_band(self) -> str | None:
        return self._repeater_config.get("lock_band")

    @property
    def scanned_networks(self) -> list[ScannedNetwork]:
        return self._scanned_networks

    @property
    def saved_networks(self) -> list[dict[str, Any]]:
        return self._saved_networks

    @property
    def last_wifi_scan(self) -> datetime | None:
        return self._last_wifi_scan

    @property
    def fan_status(self) -> FanStatus | None:
        return self._fan_status

    @property
    def fan_running(self) -> bool | None:
        if self._fan_status is None:
            return None
        return self._fan_status.running

    @property
    def fan_speed(self) -> int | None:
        if self._fan_status is None:
            return None
        if not self._fan_status.running:
            return 0
        return self._fan_status.speed

    @property
    def fan_temperature_threshold(self) -> int | None:
        if self._fan_status is None:
            return None
        return self._fan_status.temperature_threshold

    @property
    def event_device_added(self) -> str:
        return f"{DOMAIN}-device-new-{self._factory_mac}"

    @property
    def event_device_updated(self) -> str:
        return f"{DOMAIN}-device-update-{self._factory_mac}"

    @property
    def event_networks_updated(self) -> str:
        return f"{DOMAIN}-networks-update-{self._factory_mac}"

    @property
    def event_vpn_tunnels_updated(self) -> str:
        return f"{DOMAIN}-vpn-tunnels-updated-{self._factory_mac}"

    @property
    def event_cellular_traffic_config_updated(self) -> str:
        return f"{DOMAIN}-cellular-traffic-config-updated-{self._factory_mac}"
