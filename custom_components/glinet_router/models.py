from __future__ import annotations

from collections.abc import ValuesView
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any

from homeassistant.util import dt as dt_util

from .utils import get_first_int


class RepeaterState(IntEnum):
    INITIALIZING = -1
    NOT_USED = 0
    CONNECTING = 1
    CONNECTED = 2
    FAILED = 3
    WAN_AVAILABLE = 4


@dataclass(slots=True)
class RepeaterStatus:
    state: RepeaterState
    ssid: str | None = None
    bssid: str | None = None
    channel: int | None = None
    signal: int | None = None
    ipv4_address: str | None = None
    ipv4_gateway: str | None = None
    ipv4_dns: list[str] | None = None
    device: str | None = None
    fail_type: str | None = None
    eap: bool | None = None
    wifi_generation: str | None = None
    bare_mode: bool | None = None

    @classmethod
    def from_api_response(cls, data: dict) -> RepeaterStatus:
        ipv4 = data.get("ipv4") or {}
        dns_list = ipv4.get("dns")
        state = data.get("state", 0)
        try:
            repeater_state = RepeaterState(state)
        except ValueError:
            repeater_state = RepeaterState.NOT_USED
        return cls(
            state=repeater_state,
            ssid=data.get("ssid"),
            bssid=data.get("bssid"),
            channel=data.get("channel"),
            signal=data.get("signal"),
            ipv4_address=ipv4.get("ip"),
            ipv4_gateway=ipv4.get("gateway"),
            ipv4_dns=dns_list if isinstance(dns_list, list) else None,
            device=data.get("device"),
            fail_type=data.get("fail_type"),
            eap=data.get("eap"),
            wifi_generation=data.get("wifi_generation"),
            bare_mode=data.get("bare_mode"),
        )


@dataclass(slots=True)
class FanStatus:
    running: bool
    speed: int | None = None
    temperature_threshold: int | None = None
    warn_temperature: int | None = None

    @classmethod
    def from_api_response(cls, status: dict, config: dict) -> FanStatus:
        return cls(
            running=status.get("status", False),
            speed=status.get("speed"),
            temperature_threshold=config.get("temperature"),
            warn_temperature=config.get("warn_temperature"),
        )


@dataclass(slots=True)
class ScannedNetwork:
    ssid: str
    bssid: str
    signal: int
    band: str
    encryption_enabled: bool
    encryption_type: str
    saved: bool
    channel: int | None = None
    dfs: bool = False
    device: str | None = None

    @classmethod
    def from_api_response(cls, data: dict) -> ScannedNetwork:
        encryption = data.get("encryption") or {}
        return cls(
            ssid=data.get("ssid", ""),
            bssid=data.get("bssid", ""),
            signal=data.get("signal", 0),
            band=data.get("band", ""),
            encryption_enabled=encryption.get("enabled", False),
            encryption_type=encryption.get("description", "Open"),
            saved=data.get("saved", False),
            channel=data.get("channel"),
            dfs=data.get("dfs", False),
            device=data.get("device"),
        )


class DeviceInterfaceType(StrEnum):
    WIFI_24 = "2.4GHz"
    WIFI_5 = "5GHz"
    LAN = "LAN"
    WIFI_24_GUEST = "2.4GHz Guest"
    WIFI_5_GUEST = "5GHz Guest"
    UNKNOWN = "Unknown"
    DONGLE = "Dongle"
    BYPASS_ROUTE = "Bypass Route"
    UNKNOWN2 = "Unknown"
    MLO = "MLO"
    MLO_GUEST = "MLO Guest"
    WIFI_6 = "6GHz"
    WIFI_6_GUEST = "6GHz Guest"


@dataclass(slots=True)
class WireGuardClient:
    name: str
    connected: bool = field(compare=False)
    group_id: int = 0
    peer_id: int = 0
    tunnel_id: int | None = None


class VpnTunnelType(StrEnum):
    WIREGUARD = "wireguard"
    OPENVPN = "openvpn"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class VpnTunnel:
    tunnel_id: int
    name: str
    tunnel_type: VpnTunnelType
    enabled: bool = False
    connected: bool = field(compare=False, default=False)
    killswitch: bool = False
    group_id: int | None = None
    peer_id: int | None = None
    client_id: int | None = None
    via: str | None = None
    is_default: bool = False

    @classmethod
    def from_api_response(cls, data: dict, *, is_default: bool = False) -> VpnTunnel:
        via = data.get("via") or {}
        raw_type = via.get("type") or data.get("type")
        try:
            tunnel_type = VpnTunnelType(raw_type) if raw_type else VpnTunnelType.UNKNOWN
        except ValueError:
            tunnel_type = VpnTunnelType.UNKNOWN

        configs = via.get("configs") if isinstance(via, dict) else None
        group_id: int | None = None
        peer_id: int | None = None
        client_id: int | None = None
        if isinstance(configs, list) and configs:
            first = configs[0] if isinstance(configs[0], dict) else {}
            group_id = first.get("group_id")
            id_list = first.get("id_list")
            if isinstance(id_list, list) and id_list:
                raw_inner = id_list[0]
                if tunnel_type == VpnTunnelType.WIREGUARD:
                    peer_id = int(raw_inner) if raw_inner is not None else None
                elif tunnel_type == VpnTunnelType.OPENVPN:
                    client_id = int(raw_inner) if raw_inner is not None else None
        if group_id is None and isinstance(via, dict):
            group_id = via.get("group_id")
        if peer_id is None and isinstance(via, dict) and tunnel_type == VpnTunnelType.WIREGUARD:
            peer_id = via.get("peer_id")
        if client_id is None and isinstance(via, dict) and tunnel_type == VpnTunnelType.OPENVPN:
            client_id = via.get("client_id")

        tunnel_id = data.get("tunnel_id")
        return cls(
            tunnel_id=int(tunnel_id) if tunnel_id is not None else 0,
            name=str(data.get("name") or f"Tunnel {tunnel_id or ''}").strip()
            or f"Tunnel {tunnel_id or ''}",
            tunnel_type=tunnel_type,
            enabled=bool(data.get("enabled", False)),
            killswitch=bool(data.get("killswitch", False)),
            group_id=int(group_id) if group_id is not None else None,
            peer_id=int(peer_id) if peer_id is not None else None,
            client_id=int(client_id) if client_id is not None else None,
            via=str(via.get("via")) if isinstance(via, dict) and via.get("via") else None,
            is_default=is_default,
        )


@dataclass(slots=True)
class WireGuardServerStatus:
    enabled: bool
    initialization: bool
    tunnel_ip: str | None = None
    connected_peers: int = 0
    total_peers: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0

    @classmethod
    def from_api_response(cls, data: dict) -> WireGuardServerStatus:
        server = data.get("server") or {}
        peers = data.get("peers") or []
        connected_count = sum(1 for p in peers if p.get("status") == 1)
        return cls(
            enabled=server.get("status") == 1,
            initialization=server.get("initialization", False),
            tunnel_ip=server.get("tunnel_ip"),
            connected_peers=connected_count,
            total_peers=len(peers),
            rx_bytes=server.get("rx_bytes", 0),
            tx_bytes=server.get("tx_bytes", 0),
        )


@dataclass(slots=True)
class OpenVpnClient:
    name: str
    connected: bool = field(compare=False)
    group_id: int = 0
    client_id: int = 0
    group_name: str | None = None
    location: str | None = None
    locations: list[str] = field(default_factory=list)
    remotes: list[str] = field(default_factory=list)
    tunnel_id: int | None = None


@dataclass(slots=True)
class OpenVpnServerStatus:
    enabled: bool
    initialization: bool
    tunnel_ip: str | None = None
    connected_users: int = 0
    total_users: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0

    @classmethod
    def from_api_response(cls, data: dict, users: list[dict]) -> OpenVpnServerStatus:
        status = data.get("status")
        return cls(
            enabled=status == 1,
            initialization=data.get("initialization", False),
            tunnel_ip=data.get("tunnel_ip"),
            connected_users=len(users),
            total_users=len(users),
            rx_bytes=data.get("rx_bytes", 0),
            tx_bytes=data.get("tx_bytes", 0),
        )


@dataclass(slots=True)
class ZeroTierStatus:
    enabled: bool
    network_id: str | None
    connected: bool
    zerotier_ip: str | None
    lan_ip: str | None
    wan_ip: str | None

    @classmethod
    def from_api_response(cls, config: dict, status: dict) -> ZeroTierStatus:
        return cls(
            enabled=config.get("enable", False),
            network_id=config.get("id"),
            connected=status.get("status") == 0,
            zerotier_ip=status.get("zerotier_ip"),
            lan_ip=status.get("lan_ip"),
            wan_ip=status.get("wan_ip"),
        )


@dataclass(slots=True)
class AdGuardStatus:
    enabled: bool
    dns_enabled: bool

    @classmethod
    def from_api_response(cls, data: dict) -> AdGuardStatus:
        return cls(
            enabled=data.get("enabled", False),
            dns_enabled=data.get("dns_enabled", False),
        )


def _mac_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).lower() for item in value if item]
    if isinstance(value, str) and value:
        return [value.lower()]
    return []


@dataclass(slots=True)
class ParentalGroup:
    id: str
    name: str
    enabled: bool = True
    rule: str | None = None
    macs: list[str] = field(default_factory=list)
    schedules_enabled: bool = True
    brief: bool = False
    active_rule_id: str | None = None
    active_schedule_ids: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict) -> ParentalGroup:
        group_id = str(data.get("id") or data.get("group_id") or data.get(".name") or "")
        name = str(data.get("name") or data.get("alias") or group_id)
        macs = _mac_list(
            data.get("mac") or data.get("macs") or data.get("clients") or data.get("devices")
        )
        rule = data.get("rule") or data.get("rule_id")
        return cls(
            id=group_id,
            name=name,
            enabled=bool(data.get("enable", data.get("enabled", True))),
            rule=str(rule) if rule is not None else None,
            macs=macs,
            schedules_enabled=bool(
                data.get("schedule_enable", data.get("schedules_enabled", True))
            ),
            brief=bool(data.get("brief", False)),
            active_rule_id=(
                str(data.get("active_rule") or data.get("active_rule_id"))
                if data.get("active_rule") or data.get("active_rule_id")
                else None
            ),
            active_schedule_ids=[
                str(item)
                for item in (data.get("active_schedule_ids") or data.get("active_schedules") or [])
            ],
            raw=dict(data),
        )

    def with_updates(self, **updates: object) -> dict:
        data = dict(self.raw)
        data.update(updates)
        data["id"] = self.id
        return data

    def with_merged(self, other: ParentalGroup) -> ParentalGroup:
        raw = dict(self.raw)
        raw.update(other.raw)
        other_has_name = any(key in other.raw for key in ("name", "alias"))
        return ParentalGroup(
            id=other.id or self.id,
            name=other.name if other_has_name else self.name,
            enabled=other.enabled,
            rule=other.rule or self.rule,
            macs=_merge_unique(self.macs, other.macs),
            schedules_enabled=other.schedules_enabled,
            brief=other.brief or self.brief,
            active_rule_id=other.active_rule_id or self.active_rule_id,
            active_schedule_ids=_merge_unique(
                self.active_schedule_ids,
                other.active_schedule_ids,
            ),
            raw=raw,
        )


@dataclass(slots=True)
class ParentalStatus:
    enabled: bool | None = None
    mode: int | None = None
    groups: dict[str, ParentalGroup] = field(default_factory=dict)
    time_valid: bool | None = None
    raw_config: dict = field(default_factory=dict)
    raw_status: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(
        cls,
        config: dict | None,
        status: dict | None,
        mode: dict | None = None,
    ) -> ParentalStatus:
        config = config or {}
        status = status or {}
        mode = mode or {}
        groups: dict[str, ParentalGroup] = {}

        for source in (config.get("groups"), config.get("group"), status.get("groups")):
            if isinstance(source, dict):
                iterable: list[Any] | ValuesView[Any] = source.values()
            elif isinstance(source, list):
                iterable = source
            else:
                iterable = []
            for item in iterable:
                if not isinstance(item, dict):
                    continue
                group = ParentalGroup.from_api_response(item)
                if group.id:
                    groups[group.id] = groups.get(group.id, group).with_merged(group)

        return cls(
            enabled=config.get("enable", config.get("enabled")),
            mode=mode.get("mode") if isinstance(mode.get("mode"), int) else None,
            groups=groups,
            time_valid=status.get("time_valid"),
            raw_config=config,
            raw_status=status,
        )


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))


@dataclass(slots=True)
class WifiInterface:
    name: str
    enabled: bool
    ssid: str
    guest: bool
    hidden: bool
    encryption: str


class SmsDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    UNKNOWN = "unknown"


class SmsStatus(IntEnum):
    UNREAD = 0
    READ = 1
    SENT = 2
    SENDING = 3
    WAITING = 4
    FAILED = 5


@dataclass(slots=True)
class SmsMessage:
    message_id: str
    phone_number: str
    text: str
    bus: str | None = None
    slot: int | str | None = None
    status: int | None = None
    timestamp: str | None = None
    read: bool | None = None

    @property
    def direction(self) -> SmsDirection:
        if self.status is None:
            return SmsDirection.UNKNOWN
        if self.status in {SmsStatus.UNREAD, SmsStatus.READ}:
            return SmsDirection.INCOMING
        if self.status in {SmsStatus.SENT, SmsStatus.SENDING, SmsStatus.WAITING, SmsStatus.FAILED}:
            return SmsDirection.OUTGOING
        return SmsDirection.UNKNOWN

    @property
    def status_label(self) -> str:
        status_labels: dict[SmsStatus, str] = {
            SmsStatus.UNREAD: "Unread",
            SmsStatus.READ: "Read",
            SmsStatus.SENT: "Sent",
            SmsStatus.SENDING: "Sending",
            SmsStatus.WAITING: "Waiting",
            SmsStatus.FAILED: "Failed",
        }
        if self.status is None:
            return "Unknown"
        try:
            status = SmsStatus(self.status)
        except ValueError:
            return f"Unknown ({self.status})"
        return status_labels.get(status, f"Unknown ({self.status})")


@dataclass(slots=True)
class TrafficSim:
    slot: int
    sim_type: int
    traffic_total: int = 0
    limit_enabled: bool = False
    threshold: int | None = None
    unit: str | None = None
    reset_period: str | None = None
    day: int | None = None
    hour: int | None = None
    month: int | None = None
    save_to_flash: bool = False

    @property
    def threshold_bytes(self) -> int | None:
        if not self.limit_enabled or self.threshold is None or not self.unit:
            return None
        unit_multipliers = {
            "KB": 1024,
            "MB": 1024**2,
            "GB": 1024**3,
            "TB": 1024**4,
        }
        multiplier = unit_multipliers.get(self.unit.upper())
        if multiplier is None:
            return None
        try:
            return int(self.threshold) * multiplier
        except (TypeError, ValueError):
            return None

    @property
    def present(self) -> bool:
        return self.traffic_total > 0

    @property
    def days_until_reset(self) -> int | None:
        if not self.limit_enabled or not self.reset_period:
            return None
        try:
            now = dt_util.utcnow().replace(tzinfo=None)
            anchor_day = int(self.day) if self.day is not None else 1
            anchor_hour = int(self.hour) if self.hour is not None else 0
            anchor_month = int(self.month) if self.month is not None else now.month

            if self.reset_period == "day":
                next_reset = now.replace(hour=anchor_hour, minute=0, second=0, microsecond=0)
                if next_reset <= now:
                    next_reset = next_reset + timedelta(days=1)
                return (next_reset - now).days
            if self.reset_period == "week":
                iso_day = max(1, min(7, anchor_day))
                days_ahead = (iso_day - now.isoweekday()) % 7
                next_reset = now.replace(hour=anchor_hour, minute=0, second=0, microsecond=0)
                next_reset = next_reset + timedelta(days=days_ahead)
                if next_reset <= now:
                    next_reset = next_reset + timedelta(days=7)
                return (next_reset - now).days
            if self.reset_period in {"month", "season", "year"}:
                return _days_until_monthly_reset(
                    now, anchor_day, anchor_hour, anchor_month, self.reset_period
                )
        except (TypeError, ValueError):
            return None
        return None


def _days_until_monthly_reset(
    now: datetime,
    anchor_day: int,
    anchor_hour: int,
    anchor_month: int,
    period: str,
) -> int | None:
    from calendar import monthrange

    safe_anchor_day = max(1, min(28, anchor_day))
    safe_anchor_hour = max(0, min(23, anchor_hour))

    if period == "year":
        try:
            candidate = now.replace(
                month=max(1, min(12, anchor_month)),
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
        try:
            current_quarter = (now.month - 1) // 3
            candidate_month = current_quarter * 3 + max(1, min(3, anchor_month))
        except (TypeError, ValueError):
            return None
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


class ClientDeviceInfo:
    def __init__(self, mac: str, name: str | None = None) -> None:
        self._mac = mac
        self._name = name
        self._ip_address: str | None = None
        self._last_activity = dt_util.utcnow() - timedelta(days=1)
        self._connected = False
        self._interface_type = DeviceInterfaceType.UNKNOWN
        self._rx_rate: int | None = None
        self._tx_rate: int | None = None
        self._total_rx: int | None = None
        self._total_tx: int | None = None
        self._is_known = True

    def apply_update(self, dev_info: dict | None = None, consider_home: int = 0) -> None:
        now = dt_util.utcnow()
        if dev_info:
            alias = str(dev_info.get("alias", "")).strip()
            name = str(dev_info.get("name", "")).strip()
            if alias:
                self._name = alias
            elif name and name != "*":
                self._name = name
            else:
                self._name = self._mac.replace(":", "_")
            self._ip_address = dev_info.get("ip")
            self._last_activity = now
            self._connected = bool(dev_info.get("online", False))
            type_index = int(dev_info.get("type", 5))
            interface_types = list(DeviceInterfaceType)
            if 0 <= type_index < len(interface_types):
                self._interface_type = interface_types[type_index]
            else:
                self._interface_type = DeviceInterfaceType.UNKNOWN
            self._rx_rate = get_first_int(dev_info, ("rx",))
            self._tx_rate = get_first_int(dev_info, ("tx",))
            self._total_rx = get_first_int(dev_info, ("total_rx",))
            self._total_tx = get_first_int(dev_info, ("total_tx",))

        if self._connected:
            self._connected = (now - self._last_activity).total_seconds() < consider_home

        if not self._connected:
            self._ip_address = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def interface_type(self) -> DeviceInterfaceType:
        return self._interface_type

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def ip_address(self) -> str | None:
        return self._ip_address

    @property
    def last_activity(self) -> datetime:
        return self._last_activity

    @property
    def rx_rate(self) -> int | None:
        return self._rx_rate

    @property
    def tx_rate(self) -> int | None:
        return self._tx_rate

    @property
    def total_rx(self) -> int | None:
        return self._total_rx

    @property
    def total_tx(self) -> int | None:
        return self._total_tx

    @property
    def is_known(self) -> bool:
        return self._is_known

    @is_known.setter
    def is_known(self, value: bool) -> None:
        self._is_known = value
