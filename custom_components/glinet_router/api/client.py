from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from aiohttp import ClientResponse, ClientResponseError, ClientSession
from passlib.hash import md5_crypt, sha256_crypt, sha512_crypt

from .const import (
    DEFAULT_TIMEOUT,
    LONG_TIMEOUT,
)
from .exceptions import (
    APIClientError,
    AuthenticationError,
    NonZeroResponse,
    TokenError,
    UnsuccessfulRequest,
)
from .modules import (
    AdGuardModule,
    BlackWhiteListModule,
    ClientsModule,
    DiagModule,
    FanModule,
    FirewallModule,
    KmwanModule,
    LedModule,
    MacCloneModule,
    McuModule,
    ModemModule,
    Mwan3Module,
    OvpnClientModule,
    OvpnServerModule,
    ParentalControlModule,
    RepeaterModule,
    SystemModule,
    TailscaleModule,
    UpgradeModule,
    WgClientModule,
    WgServerModule,
    WifiModule,
    ZeroTierModule,
)


def _decode_firmware_version(version: str) -> tuple[int, int, int, int]:
    numbers = [int(value) for value in re.findall(r"\d+", version)]
    normalized = [*numbers, 0, 0, 0, 0][:4]
    return tuple(normalized)


async def _extract_response_data(response: ClientResponse) -> dict[str, Any] | list[Any]:
    try:
        payload = await response.json(content_type=None)
    except (ValueError, ClientResponseError) as exc:
        text = await response.text()
        raise UnsuccessfulRequest(
            f"Request failed or returned invalid JSON (status {response.status}): {text}"
        ) from exc

    if not 200 <= response.status < 300:
        raise UnsuccessfulRequest(f"Request failed with status {response.status}: {payload}")

    if "result" in payload:
        return payload["result"]

    if "error" not in payload:
        raise APIClientError(f"Unexpected response from GL.iNet router: {payload}")

    error = payload["error"]
    message = error.get("message", "null")
    code = error.get("code", 0)

    if code == -1:
        raise TokenError(f"Request returned error code -1 ({message})")
    if code == -32000:
        raise AuthenticationError(f"Request returned error code -32000 ({message})")
    if code < 0:
        raise NonZeroResponse(f"Request returned error code {code} with message: {message}")

    return payload


class GLinetApiClient:
    _firmware_version: tuple[int, int, int, int] | None = None

    def __init__(
        self,
        base_url: str,
        session: ClientSession,
        sid: str | None = None,
        verify_ssl: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ssl_setting = None if verify_ssl else False
        self._session = session
        self.sid = sid
        self._logged_in = sid is not None

        self.system = SystemModule(self)
        self.modem = ModemModule(self)
        self.mcu = McuModule(self)
        self.kmwan = KmwanModule(self)
        self.mwan3 = Mwan3Module(self)
        self.wifi = WifiModule(self)
        self.zerotier = ZeroTierModule(self)
        self.clients = ClientsModule(self)
        self.wg_client = WgClientModule(self)
        self.wg_server = WgServerModule(self)
        self.ovpn_client = OvpnClientModule(self)
        self.ovpn_server = OvpnServerModule(self)
        self.tailscale = TailscaleModule(self)
        self.repeater = RepeaterModule(self)
        self.upgrade = UpgradeModule(self)
        self.fan = FanModule(self)
        self.firewall = FirewallModule(self)
        self.led = LedModule(self)
        self.macclone = MacCloneModule(self)
        self.diag = DiagModule(self)
        self.adguard = AdGuardModule(self)
        self.parental_control = ParentalControlModule(self)
        self.black_white_list = BlackWhiteListModule(self)

    @staticmethod
    def _build_sid_payload(method: str, params: list[Any], sid: str | None) -> dict[str, Any]:
        return {
            "method": method,
            "jsonrpc": "2.0",
            "params": [sid, *params],
            "id": 0,
        }

    @staticmethod
    def _build_payload(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": method,
            "jsonrpc": "2.0",
            "params": params,
            "id": 0,
        }

    async def _ensure_firmware_version(self) -> None:
        if self._firmware_version is None:
            await self.system.get_info()

    async def _is_firmware_at_least(self, version: tuple[int, int, int, int]) -> bool:
        await self._ensure_firmware_version()
        fw_ver = self._firmware_version
        return fw_ver is not None and fw_ver >= version

    async def _send_request(
        self, payload: dict[str, Any], timeout_seconds: int = DEFAULT_TIMEOUT
    ) -> dict[str, Any] | list[Any]:
        async with self._session.post(
            self._base_url, json=payload, timeout=timeout_seconds, ssl=self._ssl_setting
        ) as response:
            return await _extract_response_data(response)

    async def _request_challenge(self, username: str) -> dict[str, Any]:
        result = await self._send_request(
            self._build_payload("challenge", {"username": username}),
            timeout_seconds=LONG_TIMEOUT,
        )
        return dict(result)

    async def _fetch_session_id(self, username: str, login_hash: str) -> dict[str, Any]:
        result = await self._send_request(
            self._build_payload("login", {"username": username, "hash": login_hash}),
            timeout_seconds=LONG_TIMEOUT,
        )
        return dict(result)

    async def is_router_reachable(self, username: str = "root") -> bool:
        try:
            return bool(await self._request_challenge(username))
        except APIClientError:
            return False

    async def authenticate(self, username: str, password: str) -> None:
        def _compute_hash(
            algorithm: int,
            salt: str,
            nonce: str,
            hash_method: str,
            login_username: str,
            login_password: str,
        ) -> str:
            if algorithm == 1:
                cipher_password = md5_crypt.using(salt=salt).hash(login_password)
            elif algorithm == 5:
                cipher_password = sha256_crypt.using(salt=salt, rounds=5000).hash(login_password)
            elif algorithm == 6:
                cipher_password = sha512_crypt.using(salt=salt, rounds=5000).hash(login_password)
            else:
                raise ValueError("Unsupported router cipher algorithm")

            data = f"{login_username}:{cipher_password}:{nonce}"
            if hash_method == "md5":
                return hashlib.md5(data.encode(), usedforsecurity=False).hexdigest()
            if hash_method == "sha256":
                return hashlib.sha256(data.encode()).hexdigest()
            if hash_method == "sha512":
                return hashlib.sha512(data.encode()).hexdigest()
            raise ValueError("Unsupported router hash algorithm")

        challenge = await self._request_challenge(username)
        login_hash = await asyncio.to_thread(
            _compute_hash,
            challenge["alg"],
            challenge["salt"],
            challenge["nonce"],
            challenge.get("hash-method", "md5"),
            username,
            password,
        )
        response = await self._fetch_session_id(username, login_hash)
        if "sid" not in response:
            raise AuthenticationError("Router login response did not include a session id")
        self.sid = str(response["sid"])
        self._logged_in = True

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    async def custom_call(
        self, method: str, params: dict[str, Any] | list[Any] | None = None
    ) -> dict[str, Any] | list[Any]:
        if params is None:
            params = {}
        if "/" in method:
            module, _, sub_method = method.partition("/")
            payload = self._build_sid_payload("call", [module, sub_method, params], self.sid)
        elif method == "call":
            if isinstance(params, list):
                payload = self._build_sid_payload("call", params, self.sid)
            else:
                payload = self._build_sid_payload("call", [params], self.sid)
        elif method in ("challenge", "login"):
            payload = self._build_payload(method, params if isinstance(params, dict) else {})
        else:
            if isinstance(params, list):
                payload = self._build_sid_payload(method, params, self.sid)
            else:
                payload = self._build_sid_payload(method, [params], self.sid)
        return await self._send_request(payload)
