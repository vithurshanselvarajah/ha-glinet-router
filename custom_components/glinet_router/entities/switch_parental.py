from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.entity import DeviceInfo

from ..const import DOMAIN
from ..hub import GLinetHub
from ..models import ClientDeviceInfo, ParentalGroup
from .switch_base import GLinetSwitchBase


class GLinetParentalControlGlobalSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:account-child"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/parental_control"

    @property
    def name(self) -> str:
        return "Parental control"

    @property
    def is_on(self) -> bool | None:
        return self._hub.parental_control_enabled

    async def async_turn_on(self, **_: Any) -> None:
        await self._safe_set(
            lambda: self._hub.set_parental_control_enabled(True),
            "Unable to enable parental control",
        )

    async def async_turn_off(self, **_: Any) -> None:
        await self._safe_set(
            lambda: self._hub.set_parental_control_enabled(False),
            "Unable to disable parental control",
        )


class GLinetParentalControlGroupSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:account-group"

    def __init__(self, hub: GLinetHub, group: ParentalGroup) -> None:
        super().__init__(hub)
        self._group = group

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/parental_control_group_{self._group.id}"

    @property
    def name(self) -> str:
        return f"Parental control {self._group.name}"

    @property
    def is_on(self) -> bool | None:
        self._group = self._hub.parental_groups.get(self._group.id, self._group)
        return self._group.enabled

    async def async_turn_on(self, **_: Any) -> None:
        await self._safe_set(
            lambda: self._hub.set_group_enabled(self._group.id, True),
            f"Unable to enable parental control group {self._group.id}",
        )

    async def async_turn_off(self, **_: Any) -> None:
        await self._safe_set(
            lambda: self._hub.set_group_enabled(self._group.id, False),
            f"Unable to disable parental control group {self._group.id}",
        )


class GLinetClientInternetAccessSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:web-check"

    def __init__(self, hub: GLinetHub, device: ClientDeviceInfo) -> None:
        super().__init__(hub)
        self._device = device
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, format_mac(device.mac))},
            name=device.name or device.mac,
            via_device=(DOMAIN, self._hub.router_id),
        )

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._device.mac}/internet_access"

    @property
    def name(self) -> str:
        return "Internet access"

    @property
    def is_on(self) -> bool | None:
        return self._hub.device_internet_access_enabled(self._device.mac)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"access_control_mode": self._hub.access_control_mode}

    async def async_turn_on(self, **_: Any) -> None:
        await self._safe_set(
            lambda: self._hub.set_single_device_block(self._device.mac, False),
            f"Unable to enable internet access for {self._device.mac}",
        )

    async def async_turn_off(self, **_: Any) -> None:
        await self._safe_set(
            lambda: self._hub.set_single_device_block(self._device.mac, True),
            f"Unable to disable internet access for {self._device.mac}",
        )
