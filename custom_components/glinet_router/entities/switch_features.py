from __future__ import annotations

import logging
from typing import Any

from .switch_base import GLinetSwitchBase

_LOGGER = logging.getLogger(__name__)


class RepeaterAutoSwitchSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:wifi-sync"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/repeater_auto_switch"

    @property
    def name(self) -> str:
        return "Repeater auto-switch networks"

    @property
    def is_on(self) -> bool | None:
        return self._hub.repeater_auto_switch

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.set_repeater_auto_switch(True)
        except OSError:
            _LOGGER.exception("Unable to enable repeater auto-switch")
            return
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.set_repeater_auto_switch(False)
        except OSError:
            _LOGGER.exception("Unable to disable repeater auto-switch")
            return
        await self._hub.async_request_refresh()


class RepeaterBareModeSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:wifi-off"
    _attr_translation_key = "repeater_bare_mode"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/repeater_bare_mode"

    @property
    def is_on(self) -> bool | None:
        return self._hub.repeater_bare_mode

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.set_repeater_bare_mode(True)
        except OSError:
            _LOGGER.exception("Unable to enable repeater bare mode")
            return
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.set_repeater_bare_mode(False)
        except OSError:
            _LOGGER.exception("Unable to disable repeater bare mode")
            return
        await self._hub.async_request_refresh()


class RepeaterSmartReconnectSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:wifi-refresh"
    _attr_translation_key = "repeater_smart_reconnect"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/repeater_smart_reconnect"

    @property
    def is_on(self) -> bool | None:
        return self._hub.repeater_smart_reconnect

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.set_repeater_smart_reconnect(True)
        except OSError:
            _LOGGER.exception("Unable to enable repeater smart reconnect")
            return
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.set_repeater_smart_reconnect(False)
        except OSError:
            _LOGGER.exception("Unable to disable repeater smart reconnect")
            return
        await self._hub.async_request_refresh()


class AdGuardEnabledSwitch(GLinetSwitchBase):
    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/adguard_enabled"

    @property
    def translation_key(self) -> str:
        return "adguard_enabled"

    @property
    def icon(self) -> str:
        return "mdi:shield-check"

    @property
    def is_on(self) -> bool | None:
        status = self._hub.adguard_status
        return status.enabled if status else None

    async def async_turn_on(self, **_: Any) -> None:
        await self._hub.set_adguard_enabled(True)
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        await self._hub.set_adguard_enabled(False)
        await self._hub.async_request_refresh()


class AdGuardDnsEnabledSwitch(GLinetSwitchBase):
    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/adguard_dns_enabled"

    @property
    def translation_key(self) -> str:
        return "adguard_dns_enabled"

    @property
    def icon(self) -> str:
        return "mdi:dns"

    @property
    def is_on(self) -> bool | None:
        status = self._hub.adguard_status
        return status.dns_enabled if status else None

    async def async_turn_on(self, **_: Any) -> None:
        await self._hub.set_adguard_dns_enabled(True)
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        await self._hub.set_adguard_dns_enabled(False)
        await self._hub.async_request_refresh()
