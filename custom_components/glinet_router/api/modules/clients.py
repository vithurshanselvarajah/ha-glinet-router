from __future__ import annotations

from typing import Any

from .base import BaseModule


def _is_online(value: Any) -> bool:

    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


class ClientsModule(BaseModule):
    async def get_list(self) -> dict[str, Any]:
        response = await self._call("clients", "get_list")
        return dict(response)

    async def get_online(self) -> dict[str, dict[str, Any]]:
        clients: dict[str, dict[str, Any]] = {}
        all_clients = await self.get_list()
        for client in all_clients.get("clients", []):
            if _is_online(client.get("online")):
                clients[str(client["mac"])] = dict(client)
        return clients

    async def clear_cache(self) -> dict[str, Any]:
        response = await self._call("clients", "clear_cache")
        return dict(response)
