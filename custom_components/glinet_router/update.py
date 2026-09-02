from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .hub import GLinetHub
from .utils import pick_first

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    _: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: GLinetHub = entry.runtime_data
    async_add_entities([GLinetFirmwareUpdateEntity(hub)], True)


def _short_release_summary(release_notes: str | None) -> str | None:
    if not release_notes:
        return None
    lines = [line.strip() for line in release_notes.splitlines() if line.strip()]
    if not lines:
        return None
    summary = lines[0]
    return summary[:255]


class GLinetFirmwareUpdateEntity(CoordinatorEntity[GLinetHub], UpdateEntity):
    _attr_has_entity_name = True
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_icon = "mdi:package-up"
    _attr_name = "Firmware"

    def __init__(self, hub: GLinetHub) -> None:
        super().__init__(hub)
        self._hub = hub
        self._attr_device_info = hub.device_info

    @property
    def unique_id(self) -> str:
        return f"glinet_update/{self._hub.device_mac}/firmware"

    @property
    def title(self) -> str:
        return "Firmware"

    @property
    def installed_version(self) -> str | None:
        return self._hub.firmware_version or None

    @property
    def latest_version(self) -> str | None:
        info = self._hub.upgrade_info
        latest = info.get("current_version")
        if latest:
            return str(latest)
        return self.installed_version

    async def async_release_notes(self) -> str | None:
        model = getattr(self._hub, "_model", "") or ""
        model = str(model).lower()
        if not model:
            return None
        return f"https://dl.gl-inet.com/router/{model}/stable"

    @property
    def release_summary(self) -> str | None:
        return None

    @property
    def auto_update(self) -> bool:
        return bool(self._hub.upgrade_config.get("upgrade_enable"))

    @property
    def supported_features(self) -> UpdateEntityFeature:
        features = UpdateEntityFeature.RELEASE_NOTES
        if self._firmware_install_payload() is not None:
            features |= UpdateEntityFeature.INSTALL
        return features

    @property
    def in_progress(self) -> bool:
        status = self._hub.upgrade_status.get("status")
        return status in {1, 6}

    @property
    def update_percentage(self) -> int | None:
        percent = self._hub.upgrade_status.get("percent")
        if percent is None:
            return None
        try:
            return int(float(percent))
        except (TypeError, ValueError):
            return None

    def _firmware_install_payload(self) -> dict[str, Any] | None:
        from .hub import _FIRMWARE_INFO_ALIASES

        info = self._hub.upgrade_info
        payload: dict[str, Any] = {
            "keep_config": True,
            "keep_package": True,
        }
        for key, aliases in _FIRMWARE_INFO_ALIASES.items():
            value = pick_first(info, aliases)
            if value is not None:
                payload[key] = value
        if "url" not in payload or "id" not in payload:
            return None
        return payload

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        keep_package = bool(kwargs.get("keep_package", True))
        await self._hub.upgrade_firmware(backup, keep_package)
