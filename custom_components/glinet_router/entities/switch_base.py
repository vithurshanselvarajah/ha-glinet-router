from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..hub import GLinetHub


class GLinetSwitchBase(CoordinatorEntity[GLinetHub], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.CONFIG
