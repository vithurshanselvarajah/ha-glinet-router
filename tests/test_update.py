from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.components.update import UpdateEntityFeature

from custom_components.glinet_router.update import GLinetFirmwareUpdateEntity


class FakeHub:
    def __init__(
        self,
        info: dict[str, Any],
        config: dict[str, Any],
        status: dict[str, Any],
    ) -> None:
        self.hass = SimpleNamespace()
        self.device_mac = "00:11:22:33:44:55"
        self.device_info = {}
        self.firmware_version = "4.0.0"
        self._model = "x3000"
        self.upgrade_info = info
        self.upgrade_config = config
        self.upgrade_status = status
        self.calls: list[tuple[bool, bool]] = []

    async def upgrade_firmware(self, keep_config: bool, keep_package: bool) -> None:
        self.calls.append((keep_config, keep_package))


def _make_entity(
    info: dict[str, Any],
    config: dict[str, Any] | None = None,
    status: dict[str, Any] | None = None,
) -> GLinetFirmwareUpdateEntity:
    return GLinetFirmwareUpdateEntity(FakeHub(info, config or {}, status or {}))


def test_update_entity_exposes_release_notes_and_install_when_download_url_exists() -> None:
    entity = _make_entity(
        {
            "current_version": "4.0.0",
            "version_new": "4.0.1",
            "release_note": "### Fixes\n* Better stability",
            "url": "http://example.invalid/fw.bin",
            "id": "fw-1",
            "size": 123,
            "sha256": "abc123",
        },
        {"upgrade_enable": True},
        {"status": 1, "percent": "42.5"},
    )

    assert entity.unique_id == "glinet_update/00:11:22:33:44:55/firmware"
    assert entity.title == "Firmware"
    assert entity.installed_version == "4.0.0"
    assert entity.latest_version == "4.0.1"
    assert entity.release_summary == "https://dl.gl-inet.com/router/x3000/stable"
    assert entity.release_notes == "https://dl.gl-inet.com/router/x3000/stable"
    assert entity.auto_update is True
    assert entity.in_progress is True
    assert entity.update_percentage == 42
    assert int(entity.supported_features) == 3


def test_update_entity_omits_install_without_download_url() -> None:
    entity = _make_entity({"version_new": "4.0.1"}, {"upgrade_enable": False}, {"status": 0})

    assert entity.supported_features == UpdateEntityFeature.RELEASE_NOTES
    assert entity.latest_version == "4.0.1"
    assert entity.auto_update is False
    assert entity.in_progress is False


async def test_update_entity_install_calls_hub_upgrade_helper() -> None:
    hub = FakeHub(
        {
            "version_new": "4.0.1",
            "release_note": "Notes",
            "url": "http://example.invalid/fw.bin",
            "id": "fw-1",
        },
        {},
        {},
    )
    entity = GLinetFirmwareUpdateEntity(hub)

    await entity.async_install("4.0.1", backup=False)

    assert hub.calls == [(False, True)]


def test_update_entity_reports_new_firmware_when_current_and_target_differ() -> None:
    hub = FakeHub(
        {
            "current_version": "4.9.0",
            "version_new": "4.10.1",
            "new_compile_time": "2026-09-18 18:54:58",
            "current_compile_time": "2026-05-15 18:37:04",
            "url": "http://example.invalid/fw.bin",
            "id": "fw-4.10.1",
        },
        {},
        {},
    )
    hub.firmware_version = "4.9.0"
    entity = GLinetFirmwareUpdateEntity(hub)

    assert entity.installed_version == "4.9.0"
    assert entity.latest_version == "4.10.1"


def test_update_entity_falls_back_to_new_version_alias() -> None:
    entity = _make_entity(
        {
            "current_version": "4.9.0",
            "new_version": "4.10.1",
            "url": "http://example.invalid/fw.bin",
            "id": "fw-4.10.1",
        },
    )

    assert entity.latest_version == "4.10.1"
