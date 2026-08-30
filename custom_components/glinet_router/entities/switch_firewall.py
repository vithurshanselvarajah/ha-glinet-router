from __future__ import annotations

import logging
from typing import Any

from ..hub import GLinetHub
from .switch_base import GLinetSwitchBase

_LOGGER = logging.getLogger(__name__)


class GLinetDMZSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:shield-off"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/firewall_dmz"

    @property
    def name(self) -> str:
        return "Firewall DMZ"

    @property
    def is_on(self) -> bool | None:
        return self._hub._dmz_config.get("enabled", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"destination_ip": self._hub._dmz_config.get("dest_ip")}

    async def async_turn_on(self, **_: Any) -> None:
        _LOGGER.warning(
            "DMZ cannot be enabled without a destination IP. Use the service to configure."
        )

    async def async_turn_off(self, **_: Any) -> None:
        await self._hub.set_dmz_config(False)
        await self._hub.async_request_refresh()


class GLinetWANAccessSwitch(GLinetSwitchBase):
    def __init__(self, hub: GLinetHub, access_type: str, name: str, icon: str) -> None:
        super().__init__(hub)
        self._access_type = access_type
        self._name = name
        self._attr_icon = icon

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/wan_access_{self._access_type}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_on(self) -> bool | None:
        return self._hub._wan_access.get(f"enable_{self._access_type}", False)

    async def async_turn_on(self, **_: Any) -> None:
        config = self._hub._wan_access.copy()
        config[f"enable_{self._access_type}"] = True
        await self._hub.set_wan_access(config)
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        config = self._hub._wan_access.copy()
        config[f"enable_{self._access_type}"] = False
        await self._hub.set_wan_access(config)
        await self._hub.async_request_refresh()
