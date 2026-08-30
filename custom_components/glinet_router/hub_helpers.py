from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.util.dt import utcnow

if TYPE_CHECKING:
    from homeassistant.helpers.entity_registry import RegistryEntry


def _merge_modem_lists(
    info_modems: list[dict[str, Any]],
    status_modems: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for modem in [*info_modems, *status_modems]:
        if not isinstance(modem, dict) or not modem.get("bus"):
            continue
        key = _modem_key(modem)
        merged[key] = merged.get(key, {}) | dict(modem)
    return list(merged.values())


def _modem_key(modem: dict[str, Any]) -> str:
    bus = str(modem["bus"])
    slot = modem.get("slot")
    if slot is None or slot == "":
        return bus
    return f"{bus}:slot:{slot}"


def _select_sms_modem(modems: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for modem in modems.values():
        if modem.get("sms_support") is True:
            return modem
    for modem in modems.values():
        if modem.get("simcard"):
            return modem
    return next(iter(modems.values()), None)


def _sms_status_is_read(status: Any) -> bool | None:
    if status == 0:
        return False
    if isinstance(status, int):
        return status in {1, 2, 3, 4, 5}
    return None


def _extract_access_macs(data: dict[str, Any], section: str, key: str) -> list[str]:
    value = data.get(key) or data.get(f"{section}_mac")
    if isinstance(value, list):
        return [str(item).lower() for item in value if item]
    section_data = data.get(section)
    if isinstance(section_data, dict):
        value = section_data.get("mac") or section_data.get("macs")
        if isinstance(value, list):
            return [str(item).lower() for item in value if item]
    if isinstance(section_data, list):
        return [str(item).lower() for item in section_data if item]
    value = data.get("mac") if data.get("mode") == section else None
    if isinstance(value, list):
        return [str(item).lower() for item in value if item]
    return []


def _access_mode_is_black(mode: str) -> bool:
    return mode in {"black", "blacklist", "deny"}


def _access_mode_is_white(mode: str) -> bool:
    return mode in {"white", "whitelist", "allow"}


def _normalise_traffic_config(
    response: dict[str, Any],
    *,
    is_firmware_4_9: bool,
) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    save_to_flash = bool(response.get("save_to_flash"))
    records: dict[int, dict[str, Any]] = {}

    def _coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _coerce_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    if is_firmware_4_9:
        traffic_items = response.get("traffic") or []
        if not isinstance(traffic_items, list):
            traffic_items = []
        for entry in traffic_items:
            if not isinstance(entry, dict):
                continue
            slot_raw = entry.get("slot")
            try:
                slot = int(slot_raw)
            except (TypeError, ValueError):
                continue
            sim_type = _coerce_int(entry.get("type"))
            traffic_total = _coerce_int(entry.get("traffic_total"))
            record = records.setdefault(
                slot,
                {
                    "slot": slot,
                    "sim_type": sim_type,
                    "traffic_total": 0,
                    "limit_enabled": False,
                    "threshold": None,
                    "unit": None,
                    "reset_period": None,
                    "day": None,
                    "hour": None,
                    "month": None,
                    "save_to_flash": save_to_flash,
                },
            )
            record["sim_type"] = sim_type
            record["traffic_total"] = traffic_total

        limit_items = response.get("limit") or []
        if isinstance(limit_items, list):
            for entry in limit_items:
                if not isinstance(entry, dict):
                    continue
                slot_raw = entry.get("slot")
                try:
                    slot = int(slot_raw)
                except (TypeError, ValueError):
                    continue
                record = records.setdefault(
                    slot,
                    {
                        "slot": slot,
                        "sim_type": _coerce_int(entry.get("type")),
                        "traffic_total": 0,
                        "limit_enabled": False,
                        "threshold": None,
                        "unit": None,
                        "reset_period": None,
                        "day": None,
                        "hour": None,
                        "month": None,
                        "save_to_flash": save_to_flash,
                    },
                )
                record["sim_type"] = _coerce_int(entry.get("type"))
                record["limit_enabled"] = bool(entry.get("enable"))
                threshold = entry.get("threshold")
                if threshold is not None:
                    try:
                        record["threshold"] = int(threshold)
                    except (TypeError, ValueError):
                        record["threshold"] = _coerce_str(threshold)
                record["unit"] = _coerce_str(entry.get("unit"))
                record["reset_period"] = _coerce_str(entry.get("reset_period"))
                day = entry.get("day")
                if day is not None:
                    try:
                        record["day"] = int(day)
                    except (TypeError, ValueError):
                        record["day"] = _coerce_str(day)
                hour = entry.get("hour")
                if hour is not None:
                    try:
                        record["hour"] = int(hour)
                    except (TypeError, ValueError):
                        record["hour"] = _coerce_str(hour)
                month = entry.get("month")
                if month is not None:
                    try:
                        record["month"] = int(month)
                    except (TypeError, ValueError):
                        record["month"] = _coerce_str(month)
    else:
        for slot in (1, 2):
            limit_block = response.get(f"sim{slot}_limit")
            traffic_total = _coerce_int(response.get(f"sim{slot}_traffic_total"))
            record = {
                "slot": slot,
                "sim_type": 0,
                "traffic_total": traffic_total,
                "limit_enabled": False,
                "threshold": None,
                "unit": None,
                "reset_period": None,
                "day": None,
                "hour": None,
                "month": None,
                "save_to_flash": save_to_flash,
            }
            if isinstance(limit_block, dict):
                record["limit_enabled"] = bool(limit_block.get("enable"))
                threshold = limit_block.get("threshold")
                if threshold is not None:
                    try:
                        record["threshold"] = int(threshold)
                    except (TypeError, ValueError):
                        record["threshold"] = _coerce_str(threshold)
                record["unit"] = _coerce_str(limit_block.get("unit"))
                record["reset_period"] = _coerce_str(limit_block.get("reset_period"))
                for field in ("day", "hour", "month"):
                    value = limit_block.get(field)
                    if value is None:
                        continue
                    try:
                        record[field] = int(value)
                    except (TypeError, ValueError):
                        record[field] = _coerce_str(value)
            records[slot] = record

    for record in records.values():
        record["save_to_flash"] = save_to_flash
        record["present"] = record["traffic_total"] > 0
        record["days_until_reset"] = _compute_days_until_reset(record)

    return [records[key] for key in sorted(records)]


def _compute_days_until_reset(record: dict[str, Any]) -> int | None:
    if not record.get("limit_enabled") or not record.get("reset_period"):
        return None
    period = str(record.get("reset_period"))
    try:
        from calendar import monthrange
        from datetime import timedelta

        now = utcnow().replace(tzinfo=None)
        day = int(record["day"]) if record.get("day") is not None else 1
        hour = int(record["hour"]) if record.get("hour") is not None else 0
        month = int(record["month"]) if record.get("month") is not None else now.month
    except (TypeError, ValueError):
        return None

    try:
        if period == "day":
            next_reset = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if next_reset <= now:
                next_reset = next_reset + timedelta(days=1)
            return (next_reset - now).days
        if period == "week":
            iso_day = max(1, min(7, day))
            days_ahead = (iso_day - now.isoweekday()) % 7
            next_reset = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            next_reset = next_reset + timedelta(days=days_ahead)
            if next_reset <= now:
                next_reset = next_reset + timedelta(days=7)
            return (next_reset - now).days
        if period in {"month", "season", "year"}:
            safe_anchor_day = max(1, min(28, day))
            safe_anchor_hour = max(0, min(23, hour))
            if period == "year":
                try:
                    candidate = now.replace(
                        month=max(1, min(12, month)),
                        day=safe_anchor_day,
                        hour=safe_anchor_hour,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                except ValueError:
                    return None
                if candidate <= now:
                    try:
                        candidate = candidate.replace(year=now.year + 1)
                    except ValueError:
                        return None
                return (candidate - now).days
            if period == "season":
                current_quarter = (now.month - 1) // 3
                candidate_month = current_quarter * 3 + max(1, min(3, month))
                try:
                    candidate = now.replace(
                        month=candidate_month,
                        day=safe_anchor_day,
                        hour=safe_anchor_hour,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                except ValueError:
                    return None
                if candidate <= now:
                    candidate = candidate + timedelta(days=92)
                return (candidate - now).days
            days_in_month = monthrange(now.year, now.month)[1]
            candidate_day = min(safe_anchor_day, days_in_month)
            try:
                candidate = now.replace(
                    day=candidate_day,
                    hour=safe_anchor_hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            except ValueError:
                return None
            if candidate <= now:
                next_month = now.month + 1
                next_year = now.year
                if next_month > 12:
                    next_month = 1
                    next_year += 1
                next_days = monthrange(next_year, next_month)[1]
                candidate = candidate.replace(
                    year=next_year,
                    month=next_month,
                    day=min(safe_anchor_day, next_days),
                )
            return (candidate - now).days
    except (ValueError, TypeError, OverflowError):
        return None
    return None


@dataclass(frozen=True)
class EntityCleanupRule:
    description: str
    matches: Callable[[RegistryEntry], bool]
    should_keep: Callable[[RegistryEntry], bool]


_FIRMWARE_INFO_ALIASES: dict[str, tuple[str, ...]] = {
    "url": ("url", "download_url", "downloadUrl", "firmware_url"),
    "id": ("id", "upgrade_id", "version_id"),
    "size": ("size", "download_size"),
    "sha256": ("sha256", "sha-256"),
}
