from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from ..const import (
    FEATURE_ADGUARD,
    FEATURE_FIREWALL,
    FEATURE_OVPN_CLIENT,
    FEATURE_OVPN_SERVER,
    FEATURE_PARENTAL_CONTROL,
    FEATURE_REPEATER,
    FEATURE_TAILSCALE,
    FEATURE_WG_CLIENT,
    FEATURE_WG_SERVER,
    FEATURE_ZEROTIER,
)
from ..hub import GLinetHub
from ..models import VpnTunnel, VpnTunnelType
from .switch_base import GLinetSwitchBase
from .switch_core import LedSwitch, WifiApSwitch
from .switch_features import (
    AdGuardDnsEnabledSwitch,
    AdGuardEnabledSwitch,
    RepeaterAutoSwitchSwitch,
    RepeaterBareModeSwitch,
    RepeaterSmartReconnectSwitch,
)
from .switch_firewall import GLinetDMZSwitch, GLinetWANAccessSwitch
from .switch_parental import (
    GLinetClientInternetAccessSwitch,
    GLinetParentalControlGlobalSwitch,
    GLinetParentalControlGroupSwitch,
)
from .switch_vpn import (
    OpenVpnClientSwitch,
    OpenVpnServerSwitch,
    TailscaleSwitch,
    VpnTunnelSwitch,
    WireGuardServerSwitch,
    WireGuardSwitch,
    ZeroTierSwitch,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


def _candidate_tunnels_for_features(hub: GLinetHub) -> list[VpnTunnel]:
    wg_enabled = hub.feature_enabled(FEATURE_WG_CLIENT)
    ovpn_enabled = hub.feature_enabled(FEATURE_OVPN_CLIENT)
    if not wg_enabled and not ovpn_enabled:
        return []
    result: list[VpnTunnel] = []
    for tunnel in hub.vpn_tunnels.values():
        if tunnel.tunnel_type == VpnTunnelType.WIREGUARD and wg_enabled:
            result.append(tunnel)
        elif tunnel.tunnel_type == VpnTunnelType.OPENVPN and ovpn_enabled:
            result.append(tunnel)
        elif tunnel.tunnel_type == VpnTunnelType.UNKNOWN and (wg_enabled or ovpn_enabled):
            result.append(tunnel)
    return result


async def async_setup_entry(
    _: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: GLinetHub = entry.runtime_data
    entities: list[SwitchEntity] = []
    dashboard_tunnels = _candidate_tunnels_for_features(hub)

    if dashboard_tunnels:
        entities.extend(VpnTunnelSwitch(hub, tunnel) for tunnel in dashboard_tunnels)
    else:
        if hub.feature_enabled(FEATURE_WG_CLIENT):
            entities.extend(WireGuardSwitch(hub, client) for client in hub.vpn_clients.values())
        if hub.feature_enabled(FEATURE_OVPN_CLIENT):
            entities.extend(
                OpenVpnClientSwitch(hub, client) for client in hub.ovpn_clients.values()
            )
    if hub.feature_enabled(FEATURE_WG_SERVER):
        entities.append(WireGuardServerSwitch(hub))
    if hub.feature_enabled(FEATURE_OVPN_SERVER):
        entities.append(OpenVpnServerSwitch(hub))
    if hub.has_tailscale and hub.feature_enabled(FEATURE_TAILSCALE):
        entities.append(TailscaleSwitch(hub))
    if hub.has_zerotier and hub.feature_enabled(FEATURE_ZEROTIER):
        entities.append(ZeroTierSwitch(hub))
    entities.extend(WifiApSwitch(hub, name, iface) for name, iface in hub.wifi_interfaces.items())
    if hub.feature_enabled(FEATURE_REPEATER):
        entities.extend(
            [
                RepeaterAutoSwitchSwitch(hub),
                RepeaterBareModeSwitch(hub),
                RepeaterSmartReconnectSwitch(hub),
            ]
        )
    if hub.feature_enabled(FEATURE_ADGUARD):
        entities.append(AdGuardEnabledSwitch(hub))
        entities.append(AdGuardDnsEnabledSwitch(hub))
    if hub.feature_enabled(FEATURE_FIREWALL):
        entities.append(GLinetDMZSwitch(hub))
        entities.append(GLinetWANAccessSwitch(hub, "ping", "WAN Ping", "mdi:access-point-network"))
        entities.append(GLinetWANAccessSwitch(hub, "https", "WAN HTTPS Access", "mdi:web"))
        entities.append(GLinetWANAccessSwitch(hub, "ssh", "WAN SSH Access", "mdi:console-network"))
    if hub.feature_enabled(FEATURE_PARENTAL_CONTROL):
        entities.append(GLinetParentalControlGlobalSwitch(hub))
        entities.extend(
            GLinetParentalControlGroupSwitch(hub, group) for group in hub.parental_groups.values()
        )
    entities.append(LedSwitch(hub))
    async_add_entities(entities, True)

    vpn_tunnel_switches: dict[int, VpnTunnelSwitch] = {
        entity._tunnel_id: entity for entity in entities if isinstance(entity, VpnTunnelSwitch)
    }

    @callback
    def _reconcile_vpn_tunnels(current_ids: set[int] | None = None) -> None:
        hass = hub.hass
        hass.async_create_task(_async_reconcile_vpn_tunnels(current_ids))

    async def _async_reconcile_vpn_tunnels(
        current_ids: set[int] | None = None,
    ) -> None:
        if current_ids is None:
            current_ids = {t.tunnel_id for t in _candidate_tunnels_for_features(hub)}

        existing_ids = set(vpn_tunnel_switches.keys())

        new_tunnels = [
            tunnel
            for tunnel in _candidate_tunnels_for_features(hub)
            if tunnel.tunnel_id not in existing_ids and tunnel.tunnel_id in current_ids
        ]
        if new_tunnels:
            new_entities = [VpnTunnelSwitch(hub, tunnel) for tunnel in new_tunnels]
            for entity in new_entities:
                vpn_tunnel_switches[entity._tunnel_id] = entity
            async_add_entities(new_entities, True)

        stale_ids = existing_ids - current_ids
        if stale_ids:
            registry = async_get_entity_registry(hub.hass)
            for stale_id in list(stale_ids):
                entity = vpn_tunnel_switches.pop(stale_id, None)
                if entity is None:
                    continue
                await entity.async_remove(force_remove=True)
                if entity.entity_id:
                    registry.async_remove(entity.entity_id)

    entry.async_on_unload(
        async_dispatcher_connect(
            hub.hass,
            hub.event_vpn_tunnels_updated,
            _reconcile_vpn_tunnels,
        )
    )

    if hub.feature_enabled(FEATURE_PARENTAL_CONTROL):
        tracked: set[str] = set()

        @callback
        def register_new_devices() -> None:
            new_entities = [
                GLinetClientInternetAccessSwitch(hub, device)
                for mac, device in hub.tracked_devices.items()
                if mac not in tracked
            ]
            for entity in new_entities:
                tracked.add(entity._device.mac)
            if new_entities:
                async_add_entities(new_entities, True)

        register_new_devices()
        entry.async_on_unload(
            async_dispatcher_connect(
                hub.hass,
                hub.event_device_added,
                register_new_devices,
            )
        )


__all__ = [
    "AdGuardDnsEnabledSwitch",
    "AdGuardEnabledSwitch",
    "GLinetClientInternetAccessSwitch",
    "GLinetDMZSwitch",
    "GLinetParentalControlGlobalSwitch",
    "GLinetParentalControlGroupSwitch",
    "GLinetSwitchBase",
    "GLinetWANAccessSwitch",
    "LedSwitch",
    "OpenVpnClientSwitch",
    "OpenVpnServerSwitch",
    "RepeaterAutoSwitchSwitch",
    "RepeaterBareModeSwitch",
    "RepeaterSmartReconnectSwitch",
    "TailscaleSwitch",
    "VpnTunnelSwitch",
    "WifiApSwitch",
    "WireGuardServerSwitch",
    "WireGuardSwitch",
    "ZeroTierSwitch",
]
