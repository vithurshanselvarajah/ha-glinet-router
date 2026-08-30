import asyncio
from typing import Any

from ..exceptions import APIClientError
from ..models import TailscaleConnection
from .base import BaseModule


class TailscaleModule(BaseModule):
    async def get_config(self) -> dict[str, Any]:
        response = await self._call("tailscale", "get_config")
        return dict(response)

    async def set_config(self, config: dict[str, Any]) -> dict[str, Any]:
        response = await self._call("tailscale", "set_config", config)
        return dict(response)

    async def get_status(self) -> dict[str, Any] | list[Any]:
        response = await self._call("tailscale", "get_status")
        if isinstance(response, list):
            return response
        return dict(response)

    async def get_connection(self) -> TailscaleConnection:
        state = await self.get_status()
        if isinstance(state, list) and not state:
            return TailscaleConnection.DISCONNECTED
        return TailscaleConnection(dict(state).get("status", 0))

    async def is_configured(self) -> bool:
        try:
            status = await self.get_status()
        except APIClientError:
            return False
        if status:
            return True
        try:
            config = await self.get_config()
            return config is not False
        except APIClientError:
            return False

    async def get_details(self) -> dict[str, Any] | None:
        if not await self.is_configured():
            return None
        config = await self.get_config()
        return {
            "config": dict(config) if isinstance(config, dict) else {},
            "connection": await self.get_connection(),
        }

    async def connect(self, depth: int = 0) -> bool:
        if depth > 10:
            raise ConnectionError("Tailscale attempted to connect 10 times with no success")
        response = await self.get_status()
        if not response:
            await self.set_config({"enabled": True})
            if depth > 0:
                await asyncio.sleep(0.3)
            return await self.connect(depth + 1)
        status = dict(response).get("status", 0)
        if status == TailscaleConnection.CONNECTED.value:
            return True
        if status == TailscaleConnection.CONNECTING.value:
            await asyncio.sleep(3)
            latest = await self.get_status()
            latest_status = dict(latest).get("status", 0) if isinstance(latest, dict) else 0
            if latest_status != TailscaleConnection.CONNECTED.value:
                raise ConnectionError(
                    "Tailscale did not become connected after reporting connecting"
                )
            return True
        if status in {
            TailscaleConnection.LOGIN_REQUIRED.value,
            TailscaleConnection.AUTHORIZATION_REQUIRED.value,
        }:
            raise ConnectionAbortedError("Tailscale authorization is incomplete")
        raise ConnectionError(f"Unknown tailscale status: {status}")

    async def disconnect(self, depth: int = 0) -> bool:
        if depth > 10:
            raise ConnectionError("Tailscale attempted to disconnect 10 times with no success")
        response = await self.get_status()
        if not response:
            return True
        status = dict(response).get("status", 0)
        if status in {
            TailscaleConnection.CONNECTED.value,
            TailscaleConnection.CONNECTING.value,
        }:
            await self.set_config({"enabled": False})
            if depth > 0:
                await asyncio.sleep(0.3)
            return await self.disconnect(depth + 1)
        if status in {
            TailscaleConnection.LOGIN_REQUIRED.value,
            TailscaleConnection.AUTHORIZATION_REQUIRED.value,
        }:
            raise ConnectionAbortedError("Tailscale authorization is incomplete")
        return True
