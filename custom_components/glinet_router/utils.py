from typing import Any


def compute_mac_offset(mac: str, delta: int, sep: str = ":") -> str:
    hex_str = mac.replace(sep, "").replace("-", "").lower()
    value = int(hex_str, 16)
    value = (value + delta) & ((1 << 48) - 1)
    new_hex = f"{value:012x}"
    return sep.join(new_hex[index : index + 2] for index in range(0, 12, 2)).lower()


def pick_first(data: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = data.get(alias)
        if value is not None:
            return value
    return None


def get_first_int(data: Any, keys: tuple[str, ...], nested: tuple[str, ...] = ()) -> int | None:
    for source in _candidate_dicts(data, nested):
        for key in keys:
            value = source.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
    return None


def get_first_value(data: Any, keys: tuple[str, ...], nested: tuple[str, ...] = ()) -> str | None:
    for source in _candidate_dicts(data, nested):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _candidate_dicts(data: Any, nested: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    candidates = [data]
    for key in nested:
        value = data.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.extend(_walk_nested_dicts(data))
    return candidates


def _walk_nested_dicts(value: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for child in value.values():
            if isinstance(child, dict):
                candidates.append(child)
                candidates.extend(_walk_nested_dicts(child))
            elif isinstance(child, list):
                candidates.extend(_walk_nested_dicts(child))
    elif isinstance(value, list):
        for child in value:
            candidates.extend(_walk_nested_dicts(child))
    return candidates


def channel_to_band(channel: int | None) -> str | None:
    if channel is None:
        return None
    if 1 <= channel <= 14:
        return "2_4ghz"
    if 36 <= channel <= 177:
        return "5ghz"
    return None
