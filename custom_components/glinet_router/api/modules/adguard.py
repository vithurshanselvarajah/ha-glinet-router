from typing import Any

from .base import BaseModule


class AdGuardModule(BaseModule):
    async def get_config(self) -> dict[str, Any]:
        return await self._call("adguardhome", "get_config")

    async def set_config(self, enabled: bool, dns_enabled: bool) -> None:
        params: dict[str, Any] = {"enabled": enabled, "dns_enabled": dns_enabled}
        await self._call("adguardhome", "set_config", params)
