from __future__ import annotations

from typing import Any

import pytest

from custom_components.glinet_router.models import (
    ClientDeviceInfo,
    DeviceInterfaceType,
    FanStatus,
    RepeaterState,
    RepeaterStatus,
    ScannedNetwork,
    SmsDirection,
    SmsMessage,
    SmsStatus,
)


def test_client_device_uses_alias_before_name() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "alias": "Preferred name",
            "name": "Fallback name",
            "ip": "192.168.8.20",
            "online": True,
            "type": 1,
        }
    )

    assert device.name == "Preferred name"
    assert device.ip_address == "192.168.8.20"
    assert device.is_connected is True
    assert device.interface_type == DeviceInterfaceType.WIFI_5


def test_client_device_falls_back_to_mac_when_name_is_missing() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update({"alias": "", "name": "*", "online": True, "type": 999})

    assert device.name == "aa_bb_cc_dd_ee_ff"
    assert device.interface_type == DeviceInterfaceType.UNKNOWN


def test_client_device_ignores_non_rx_tx_bandwidth_keys() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "rx_bytes": 1000,
            "tx_bytes": 2000,
            "download_speed": 300,
            "up_speed": 400,
        }
    )

    assert device.rx_rate is None
    assert device.tx_rate is None


def test_client_device_uses_total_rx_tx_as_total_counters() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "total_rx": 1024,
            "total_tx": 2048,
        }
    )

    assert device.total_rx == 1024
    assert device.total_tx == 2048


def test_client_device_uses_rx_tx_as_explicit_rate() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "rx": 2,
            "tx": 21,
        }
    )

    assert device.rx_rate == 2
    assert device.tx_rate == 21


def test_client_device_prefers_rx_tx_over_rx_rate_tx_rate() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "rx": 7,
            "tx": 11,
            "rx_rate": 100,
            "tx_rate": 200,
        }
    )

    assert device.rx_rate == 7
    assert device.tx_rate == 11


def test_client_device_ignores_rx_rate_tx_rate_keys() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "rx_rate": 100,
            "tx_rate": 200,
        }
    )

    assert device.rx_rate is None
    assert device.tx_rate is None


def test_sms_message_direction_incoming() -> None:
    msg = SmsMessage(message_id="1", phone_number="123", text="hi", status=SmsStatus.UNREAD)
    assert msg.direction == SmsDirection.INCOMING

    msg.status = SmsStatus.READ
    assert msg.direction == SmsDirection.INCOMING


def test_sms_message_direction_outgoing() -> None:
    msg = SmsMessage(message_id="1", phone_number="123", text="hi", status=SmsStatus.SENT)
    assert msg.direction == SmsDirection.OUTGOING

    msg.status = SmsStatus.SENDING
    assert msg.direction == SmsDirection.OUTGOING

    msg.status = SmsStatus.WAITING
    assert msg.direction == SmsDirection.OUTGOING

    msg.status = SmsStatus.FAILED
    assert msg.direction == SmsDirection.OUTGOING


def test_sms_message_direction_unknown() -> None:
    msg = SmsMessage(message_id="1", phone_number="123", text="hi", status=None)
    assert msg.direction == SmsDirection.UNKNOWN

    msg.status = 999
    assert msg.direction == SmsDirection.UNKNOWN


def test_sms_message_status_label() -> None:
    msg = SmsMessage(message_id="1", phone_number="123", text="hi", status=SmsStatus.UNREAD)
    assert msg.status_label == "Unread"

    msg.status = SmsStatus.SENT
    assert msg.status_label == "Sent"

    msg.status = SmsStatus.FAILED
    assert msg.status_label == "Failed"

    msg.status = None
    assert msg.status_label == "Unknown"

    msg.status = 999
    assert msg.status_label == "Unknown (999)"


def test_client_device_ignores_byte_deltas_when_rx_tx_are_missing() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")
    device.apply_update({"online": True, "rx_bytes": 1000, "tx_bytes": 2000})

    assert device.rx_rate is None
    assert device.tx_rate is None


def test_client_device_preserves_explicit_zero_rate() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "rx": 0,
            "tx": 0,
        }
    )

    assert device.rx_rate == 0
    assert device.tx_rate == 0


def test_client_device_ignores_byte_counters_when_rx_tx_are_missing() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "rx_bytes": 1000,
            "tx_bytes": 2000,
        }
    )

    assert device.rx_rate is None
    assert device.tx_rate is None


def test_client_device_consider_home_keeps_recent_device_connected() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")
    device.apply_update({"online": True})

    device.apply_update(None, consider_home=900)

    assert device.is_connected is True
    assert device.ip_address is None


def test_client_device_marks_missing_device_away_when_delay_is_zero() -> None:
    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")
    device.apply_update({"online": True})

    device.apply_update(None, consider_home=0)

    assert device.is_connected is False


def test_client_device_fresh_online_is_connected_when_delay_is_zero() -> None:

    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update(
        {
            "online": True,
            "ip": "192.168.8.20",
            "mac": "aa:bb:cc:dd:ee:ff",
        },
        consider_home=0,
    )

    assert device.is_connected is True
    assert device.ip_address == "192.168.8.20"


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),
        ("1", True),
        ("0", False),
        ("yes", True),
        ("on", True),
        (1, True),
        (0, False),
        (None, False),
        ("", False),
        ("maybe", False),
    ],
)
def test_client_device_accepts_legacy_and_new_online_payloads(
    raw_value: Any, expected: bool
) -> None:

    device = ClientDeviceInfo("aa:bb:cc:dd:ee:ff")

    device.apply_update({"online": raw_value, "ip": "192.168.8.20"}, consider_home=0)

    assert device.is_connected is expected
    if expected:
        assert device.ip_address == "192.168.8.20"
    else:
        assert device.ip_address is None


def test_fan_status_from_api_response() -> None:
    status = {"status": True, "speed": 1000}
    config = {"temperature": 75, "warn_temperature": 90}
    fan = FanStatus.from_api_response(status, config)
    assert fan.running is True
    assert fan.speed == 1000
    assert fan.temperature_threshold == 75
    assert fan.warn_temperature == 90


def test_repeater_status_from_advanced_response() -> None:
    status = RepeaterStatus.from_api_response(
        {
            "state": 4,
            "ssid": "Example",
            "eap": True,
            "wifi_generation": "6",
            "bare_mode": False,
            "ipv4": {"ip": "192.168.8.2/24", "dns": ["1.1.1.1"]},
        }
    )

    assert status.state is RepeaterState.WAN_AVAILABLE
    assert status.eap is True
    assert status.wifi_generation == "6"
    assert status.bare_mode is False
    assert status.ipv4_dns == ["1.1.1.1"]


def test_scanned_network_from_advanced_response() -> None:
    network = ScannedNetwork.from_api_response(
        {
            "ssid": "Example",
            "bssid": "00:11:22:33:44:55",
            "signal": -55,
            "band": "5g",
            "saved": True,
            "channel": 100,
            "dfs": True,
            "device": "radio1",
            "encryption": {"enabled": True, "description": "WPA2 PSK"},
        }
    )

    assert network.dfs is True
    assert network.device == "radio1"
