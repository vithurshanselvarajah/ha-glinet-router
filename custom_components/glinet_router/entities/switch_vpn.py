from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..hub import GLinetHub
from ..models import OpenVpnClient, VpnTunnel, VpnTunnelType, WireGuardClient
from .switch_base import GLinetSwitchBase

_LOGGER = logging.getLogger(__name__)


class TailscaleSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:vpn"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/tailscale"

    @property
    def name(self) -> str:
        return "Tailscale"

    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._hub.has_tailscale

    @property
    def entity_registry_visible_default(self) -> bool:
        return self._hub.has_tailscale

    @property
    def is_on(self) -> bool | None:
        return self._hub.tailscale_connected

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.connect_tailscale()
        except OSError:
            _LOGGER.exception("Unable to enable tailscale connection")
            return
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.disconnect_tailscale()
        except OSError:
            _LOGGER.exception("Unable to stop tailscale connection")
            return
        await self._hub.async_request_refresh()


class WireGuardSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:vpn"

    def __init__(self, hub: GLinetHub, client: WireGuardClient) -> None:
        super().__init__(hub)
        self._client = client

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/{self._client.name}/wireguard_client"

    @property
    def name(self) -> str:
        return f"WG Client {self._client.name}"

    @property
    def is_on(self) -> bool | None:
        current = self._hub.vpn_clients.get(self._client.peer_id)
        if current is not None:
            self._client = current
        return self._client.connected

    async def async_turn_on(self, **_: Any) -> None:
        try:
            if (
                self._client.tunnel_id is None
                and self._hub.connected_vpn_clients is not None
                and self._client not in self._hub.connected_vpn_clients
            ):
                for client in self._hub.connected_vpn_clients:
                    await self._hub.stop_vpn_client(client.group_id, client.peer_id)

            await self._hub.start_vpn_client(
                self._client.group_id,
                self._client.peer_id,
            )
        except OSError:
            _LOGGER.exception("Unable to enable WireGuard client")
            return
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.stop_vpn_client(
                self._client.group_id,
                self._client.peer_id,
            )
        except OSError:
            _LOGGER.exception("Unable to stop WireGuard client")
            return
        await self._hub.async_request_refresh()


class WireGuardServerSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:vpn"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/wg_server"

    @property
    def name(self) -> str:
        return "WG Server"

    @property
    def is_on(self) -> bool | None:
        status = self._hub.wg_server_status
        return status.enabled if status else None

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.start_wg_server()
        except OSError:
            _LOGGER.exception("Unable to start WireGuard server")
            return
        await asyncio.sleep(10)
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.stop_wg_server()
        except OSError:
            _LOGGER.exception("Unable to stop WireGuard server")
            return
        await asyncio.sleep(10)
        await self._hub.async_request_refresh()


class OpenVpnClientSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:vpn"

    def __init__(self, hub: GLinetHub, client: OpenVpnClient) -> None:
        super().__init__(hub)
        self._client = client

    @property
    def unique_id(self) -> str:
        key = f"{self._client.group_id}_{self._client.client_id}"
        return f"glinet_switch/{self._hub.device_mac}/{key}/ovpn_client"

    @property
    def name(self) -> str:
        name = f"OpenVPN {self._client.name}"
        if self._client.group_name:
            name = f"OpenVPN {self._client.group_name} {self._client.name}"
        return name

    @property
    def is_on(self) -> bool | None:
        key = f"{self._client.group_id}_{self._client.client_id}"
        current = self._hub.ovpn_clients.get(key)
        if current is not None:
            self._client = current
        return self._client.connected

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.start_ovpn_client(
                self._client.group_id,
                self._client.client_id,
            )
        except OSError:
            _LOGGER.exception("Unable to enable OpenVPN client")
            return
        await asyncio.sleep(10)
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.stop_ovpn_client(
                self._client.group_id, self._client.client_id, self._client.tunnel_id
            )
        except OSError:
            _LOGGER.exception("Unable to stop OpenVPN client")
            return
        await asyncio.sleep(10)
        await self._hub.async_request_refresh()


class VpnTunnelSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:vpn"

    def __init__(self, hub: GLinetHub, tunnel: VpnTunnel) -> None:
        super().__init__(hub)
        self._tunnel_id = tunnel.tunnel_id
        self._tunnel_type = tunnel.tunnel_type
        self._cached_tunnel = tunnel

    def _current_tunnel(self) -> VpnTunnel | None:
        tunnel = self._hub.vpn_tunnels.get(self._tunnel_id)
        if tunnel is not None:
            self._cached_tunnel = tunnel
        return tunnel

    @property
    def _tunnel(self) -> VpnTunnel:
        return self._current_tunnel() or self._cached_tunnel

    @property
    def unique_id(self) -> str:
        if self._tunnel_type in {VpnTunnelType.WIREGUARD, VpnTunnelType.OPENVPN}:
            type_token = "wg" if self._tunnel_type == VpnTunnelType.WIREGUARD else "ovpn"
            return f"glinet_switch/{self._hub.device_mac}/vpn_tunnel/{type_token}/{self._tunnel_id}"
        return f"glinet_switch/{self._hub.device_mac}/vpn_tunnel/unknown/{self._tunnel_id}"

    @property
    def name(self) -> str:
        tunnel = self._tunnel
        tunnel_name = tunnel.name or f"Tunnel {self._tunnel_id}"
        if self._tunnel_type == VpnTunnelType.WIREGUARD:
            return f"WG Tunnel {tunnel_name}"
        if self._tunnel_type == VpnTunnelType.OPENVPN:
            return f"OpenVPN Tunnel {tunnel_name}"
        return f"VPN Tunnel {tunnel_name}"

    @property
    def is_on(self) -> bool | None:
        return self._tunnel.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tunnel = self._tunnel
        return {
            "tunnel_id": tunnel.tunnel_id,
            "tunnel_type": tunnel.tunnel_type.value,
            "connected": tunnel.connected,
            "killswitch": tunnel.killswitch,
            "is_default": tunnel.is_default,
            "via": tunnel.via,
        }

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.set_vpn_tunnel(self._tunnel_id, True)
        except OSError:
            _LOGGER.exception("Unable to enable VPN tunnel %s", self._tunnel_id)
            return
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.set_vpn_tunnel(self._tunnel_id, False)
        except OSError:
            _LOGGER.exception("Unable to disable VPN tunnel %s", self._tunnel_id)
            return
        await self._hub.async_request_refresh()


class OpenVpnServerSwitch(GLinetSwitchBase):
    _attr_icon = "mdi:vpn"

    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/ovpn_server"

    @property
    def name(self) -> str:
        return "OpenVPN Server"

    @property
    def is_on(self) -> bool | None:
        status = self._hub.ovpn_server_status
        return status.enabled if status else None

    async def async_turn_on(self, **_: Any) -> None:
        try:
            await self._hub.start_ovpn_server()
        except OSError:
            _LOGGER.exception("Unable to start OpenVPN server")
            return
        await asyncio.sleep(10)
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        try:
            await self._hub.stop_ovpn_server()
        except OSError:
            _LOGGER.exception("Unable to stop OpenVPN server")
            return
        await asyncio.sleep(10)
        await self._hub.async_request_refresh()


class ZeroTierSwitch(GLinetSwitchBase):
    @property
    def unique_id(self) -> str:
        return f"glinet_switch/{self._hub.device_mac}/zerotier"

    @property
    def name(self) -> str:
        return "ZeroTier"

    @property
    def icon(self) -> str:
        return "mdi:lan-connect"

    @property
    def is_on(self) -> bool | None:
        if self._hub.zerotier_status is None:
            return None
        return self._hub.zerotier_status.enabled

    async def async_turn_on(self, **_: Any) -> None:
        await self._hub.start_zerotier()
        await self._hub.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        await self._hub.stop_zerotier()
        await self._hub.async_request_refresh()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = self._hub.zerotier_status
        return bool(status and status.network_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if status := self._hub.zerotier_status:
            attrs = {
                "network_id": status.network_id,
                "connected": status.connected,
                "zerotier_ip": status.zerotier_ip,
                "lan_ip": status.lan_ip,
                "wan_ip": status.wan_ip,
            }
            if not status.network_id:
                attrs["note"] = "Add ZeroTier Network ID in router settings"
            return attrs
        return {}
