from __future__ import annotations

from typing import Any

from ..hub import GLinetHub
from ..models import WifiInterface
from .switch_base import GLinetSwitchBase


class WifiApSwitch(GLinetSwitchBase):
    def __init__(self, hub: GLinetHub, iface_name: str, iface: WifiInterface) -> None:
        super().__init__(hub)
        self._iface_name = iface_name
        self._iface = iface

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/iface_{self._iface_name}"

    @property
    def name(self) -> str:
        return self._iface.ssid or self._iface.name

    @property
    def is_on(self) -> bool | None:
        self._iface = self._hub.wifi_interfaces.get(self._iface_name, self._iface)
        return self._iface.enabled

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        return {
            "interface": self._iface.name,
            "guest": self._iface.guest,
            "ssid": self._iface.ssid,
            "hidden": self._iface.hidden,
            "encryption": self._iface.encryption,
        }

    async def async_turn_on(self, **_: Any) -> None:
        await self._safe_set(
            self._hub.set_wifi_interface_enabled,
            f"Unable to enable WiFi interface {self._iface_name}",
            self._iface_name,
            True,
        )

    async def async_turn_off(self, **_: Any) -> None:
        await self._safe_set(
            self._hub.set_wifi_interface_enabled,
            f"Unable to disable WiFi interface {self._iface_name}",
            self._iface_name,
            False,
        )


class LedSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:led-on"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/led"

    @property
    def name(self) -> str:
        return "System LED"

    @property
    def is_on(self) -> bool | None:
        return self._hub.led_enabled

    async def async_turn_on(self, **_: Any) -> None:
        await self._hub.set_led_enabled(True)
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        await self._hub.set_led_enabled(False)
        await self._hub.async_request_refresh()
