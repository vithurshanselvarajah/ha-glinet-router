from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..hub import GLinetHub

_LOGGER = logging.getLogger(__name__)

VPN_SETTLE_DELAY = 10


class GLinetSwitchBase(CoordinatorEntity[GLinetHub], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.CONFIG

    async def _safe_set(
        self,
        op: Callable[..., Awaitable[Any]],
        failure_label: str,
        *args: Any,
    ) -> bool:
        try:
            await op(*args)
        except OSError:
            _LOGGER.exception("%s", failure_label)
            return False
        await self._hub.async_request_refresh()
        return True

    async def _safe_set_with_delay(
        self,
        op: Callable[..., Awaitable[Any]],
        failure_label: str,
        *args: Any,
    ) -> bool:
        try:
            await op(*args)
        except OSError:
            _LOGGER.exception("%s", failure_label)
            return False
        await asyncio.sleep(VPN_SETTLE_DELAY)
        await self._hub.async_request_refresh()
        return True
