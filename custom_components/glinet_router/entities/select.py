from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import FEATURE_PARENTAL_CONTROL, FEATURE_REPEATER
from ..hub import GLinetHub
from ..models import ClientDeviceInfo, ScannedNetwork

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

NONE_SELECTED = "-- Select Network --"
HEADER_KNOWN = "-- Known Networks --"
HEADER_AVAILABLE = "-- Available Networks --"


BAND_AUTO = "Auto"
BAND_5GHZ = "5GHz"
BAND_24GHZ = "2.4GHz"

BAND_OPTIONS = [BAND_AUTO, BAND_5GHZ, BAND_24GHZ]
BAND_TO_API = {BAND_AUTO: None, BAND_5GHZ: "5g", BAND_24GHZ: "2g"}
API_TO_BAND = {None: BAND_AUTO, "5g": BAND_5GHZ, "2g": BAND_24GHZ}


async def async_setup_entry(
    _: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: GLinetHub = entry.runtime_data
    entities: list[SelectEntity] = []
    if hub.feature_enabled(FEATURE_REPEATER):
        entities.extend([WifiNetworkSelect(hub), RepeaterBandSelect(hub)])

    async_add_entities(entities, True)

    if hub.feature_enabled(FEATURE_PARENTAL_CONTROL):
        tracked: set[str] = set()

        @callback
        def register_new_devices() -> None:
            new_entities = [
                GLinetClientParentalGroupSelect(hub, device)
                for mac, device in hub.tracked_devices.items()
                if mac not in tracked
            ]
            for entity in new_entities:
                tracked.add(entity._device.mac)
            if new_entities:
                async_add_entities(new_entities, True)

        register_new_devices()
        entry.async_on_unload(
            async_dispatcher_connect(
                hub.hass,
                hub.event_device_added,
                register_new_devices,
            )
        )


class WifiNetworkSelect(CoordinatorEntity[GLinetHub], SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "WiFi network"
    _attr_icon = "mdi:wifi"
    _attr_current_option: str | None = None

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info
        self._selected_ssid: str | None = None

    @property
    def unique_id(self) -> str:
        return f"glinet_select/{self._hub.device_mac}/wifi_network"

    @property
    def options(self) -> list[str]:
        options_list: list[str] = [NONE_SELECTED]
        seen: set[str] = set()

        saved = self._hub.saved_networks
        if saved:
            options_list.append(HEADER_KNOWN)
            for saved_network in saved:
                ssid_raw = saved_network.get("ssid")
                if not isinstance(ssid_raw, str) or not ssid_raw or ssid_raw in seen:
                    continue
                seen.add(ssid_raw)
                options_list.append(ssid_raw)

        scanned: list[ScannedNetwork] = list(self._hub.scanned_networks)
        available_ssids: list[str] = []
        sorted_networks: list[ScannedNetwork] = sorted(
            scanned, key=lambda n: n.signal, reverse=True
        )
        for network in sorted_networks:
            if network.ssid and network.ssid not in seen:
                seen.add(network.ssid)
                available_ssids.append(network.ssid)

        if available_ssids:
            options_list.append(HEADER_AVAILABLE)
            options_list.extend(available_ssids)

        return options_list

    @property
    def current_option(self) -> str | None:
        status = self._hub.repeater_status
        if status and status.ssid:
            return status.ssid
        return self._selected_ssid or NONE_SELECTED

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        scanned = self._hub.scanned_networks
        saved = self._hub.saved_networks

        attrs: dict[str, Any] = {
            "known_count": len(saved),
            "scanned_count": len(set(n.ssid for n in scanned if n.ssid)),
            "last_scan": self._hub.last_wifi_scan,
        }

        selected = self.current_option
        if selected and selected not in (NONE_SELECTED, HEADER_KNOWN, HEADER_AVAILABLE):
            for network in scanned:
                if network.ssid == selected:
                    attrs["selected_signal"] = network.signal
                    attrs["selected_band"] = network.band
                    attrs["selected_channel"] = network.channel
                    attrs["selected_encryption"] = network.encryption_type
                    attrs["selected_saved"] = network.saved
                    break

        return attrs

    def _is_header(self, option: str) -> bool:
        return option in (NONE_SELECTED, HEADER_KNOWN, HEADER_AVAILABLE)

    def _is_saved_network(self, ssid: str) -> bool:
        return any(n.get("ssid") == ssid for n in self._hub.saved_networks)

    def _get_scanned_network(self, ssid: str) -> Any | None:
        for network in self._hub.scanned_networks:
            if network.ssid == ssid:
                return network
        return None

    async def async_select_option(self, option: str) -> None:
        if self._is_header(option):
            self._selected_ssid = None
            return

        self._selected_ssid = option

        if self._is_saved_network(option):
            _LOGGER.info("Connecting to saved network: %s", option)
            await self._hub.connect_to_wifi(ssid=option, remember=True)
            return

        scanned_network = self._get_scanned_network(option)
        if scanned_network and not scanned_network.encryption_enabled:
            _LOGGER.info("Connecting to open network: %s", option)
            await self._hub.connect_to_wifi(ssid=option, remember=False)
        else:
            _LOGGER.info(
                "Network '%s' requires password - use connect_wifi service to connect",
                option,
            )


class RepeaterBandSelect(CoordinatorEntity[GLinetHub], SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Repeater band"
    _attr_icon = "mdi:wifi-settings"
    _attr_options = BAND_OPTIONS

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_select/{self._hub.device_mac}/repeater_band"

    @property
    def current_option(self) -> str | None:
        band = self._hub.repeater_band
        return API_TO_BAND.get(band, BAND_AUTO)

    async def async_select_option(self, option: str) -> None:
        api_value = BAND_TO_API.get(option)
        await self._hub.set_repeater_band(api_value)
        self.async_write_ha_state()


class GLinetClientParentalGroupSelect(CoordinatorEntity[GLinetHub], SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Parental control group"
    _attr_icon = "mdi:account-child-circle"

    def __init__(self, hub: GLinetHub, device: ClientDeviceInfo) -> None:
        super().__init__(hub)
        self._hub = hub
        self._device = device
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, format_mac(device.mac))},
            name=device.name or device.mac,
            via_device_id=hub.router_device_id,  # type: ignore[typeddict-item]
        )

    @property
    def unique_id(self) -> str:
        return f"glinet_select/{self._device.mac}/parental_control_group"

    @property
    def options(self) -> list[str]:
        return ["None", *[group.name for group in self._hub.parental_groups.values()]]

    @property
    def current_option(self) -> str | None:
        group = self._hub.parental_group_for_device(self._device.mac)
        return group.name if group else "None"

    async def async_select_option(self, option: str) -> None:
        group = None if option == "None" else option
        await self._hub.assign_device_to_parental_group(self._device.mac, group)
        await self._hub.async_request_refresh()
