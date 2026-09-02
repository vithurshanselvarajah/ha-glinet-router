from __future__ import annotations

import re


def decode_firmware_version(version: str) -> tuple[int, int, int, int]:
    numbers: list[int] = [int(value) for value in re.findall(r"\d+", version)]
    normalized: list[int] = [*numbers, 0, 0, 0, 0][:4]
    return tuple(normalized)  # type: ignore[return-value]
