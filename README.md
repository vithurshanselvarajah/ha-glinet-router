# glinet-router

Unified GL.iNet support for Home Assistant.

[![GitHub Release](https://img.shields.io/github/v/release/vithurshanselvarajah/ha-glinet-router?style=flat-square)](https://github.com/vithurshanselvarajah/ha-glinet-router/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/vithurshanselvarajah/ha-glinet-router?style=flat-square)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-7289DA?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/Metvr5hC3m)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

This integration brings GL.iNet routers into Home Assistant in a practical way. It gives you router status, device tracking, controls for common features, and optional support for VPNs, SMS, repeater mode, firewall tools, and more.

---

## Quick Links
- [User Documentation & Feature Details](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki)
- [Installation Guide](#installation)
- [Setup & Configuration](#setup)
- [Join our Discord](https://discord.gg/Metvr5hC3m)

---

## Features
This integration gives you a lot of useful router data and controls out of the box. The tables below are meant to make the available options easier to scan.

### Core features

| Capability | Details | Docs |
| --- | --- | --- |
| Config flow & discovery | Easy setup with DHCP discovery support and router URL/password configuration | [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) |
| Router metadata | Model, firmware version, and MAC address information | [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) |
| System monitoring | CPU temperature, load averages, memory usage, flash usage, and uptime sensors | [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) |
| WAN monitoring | Per-interface WAN status sensors for Ethernet, Repeater, Cellular, and Tethering, reported as Up, Down, or Unknown | [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) |
| Wi-Fi controls | Switches to enable or disable each configured Wi-Fi interface | [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) |
| Hardware controls | System LED toggle and immediate reboot button | [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) |
| Device tracking | Tracks connected clients with MAC address, name/alias, IP, interface type, and last-seen timestamp, including stale-device cleanup | [Entity Reference](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/entities) |
| Client diagnostics | Per-client upload rate, download rate, and IP address sensors | [Entity Reference](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/entities) |
| Unknown device management | Discover unknown devices, auto-cleanup rules, allow/blocklist controls, and manual MAC address entries | [Unknown Device Management](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/unknown-devices) |
| Firmware & diagnostics | Native Home Assistant firmware update entity, release notes support, and sanitized diagnostics export | [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) |

### Optional modules

| Module | What it adds | Docs |
| --- | --- | --- |
| Cellular | Cellular signal and network sensors, plus modem diagnostics | [Cellular](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/cellular) |
| Repeater | Scan nearby Wi-Fi networks, connect or disconnect, and manage saved networks | [Repeater](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/repeater) |
| SMS | Send, receive, and delete text messages from the router's SIM card | [SMS](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/sms) |
| VPNs | WireGuard client/server, OpenVPN client/server, Tailscale, and ZeroTier toggles | [WireGuard Client](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/wireguard-client), [WireGuard Server](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/wireguard-server), [OpenVPN Client](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/openvpn-client), [OpenVPN Server](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/openvpn-server), [Tailscale](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/tailscale), [ZeroTier](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/zerotier) |
| AdGuard Home | Enable or disable AdGuard Home and DNS redirection | [AdGuard Home](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/adguard-home) |
| Firewall & WAN policy | DMZ, port forwarding, custom firewall rules, WAN access controls, and KMWAN/MWAN3 actions | [Firewall](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/firewall), [Router API](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/router-api) |
| Smart fan controls | Monitor fan status and speed, and set temperature thresholds | [Smart Fan Controls](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/smart-fan) |
| MCU Battery | Monitor battery status and configure high/low temperature warnings | [MCU Battery](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/mcu-battery) |
| MCU OLED | Configure what is displayed on the router's OLED screen | [MCU OLED](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/mcu-oled) |
| Parental & access control | Internet access blocks and filtering rules per client | [Parental & Access Control](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/parental-control) |
| API playground | Send custom JSON-RPC or ubus commands and inspect the response | [API Playground](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/playground) |

You can turn optional features on or off during setup, or later from the Configure menu. Unsupported features on your router model will simply be skipped.

---

## Installation

### Using HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=vithurshanselvarajah&repository=ha-glinet-router)

1. Open HACS in Home Assistant.
2. Search for GL.iNet Router.
3. Click Download, then restart Home Assistant once the install finishes.

### Manual Installation
1. Download the latest source code or release ZIP.
2. Extract the `custom_components/glinet_router` directory.
3. Copy the `glinet_router` folder into Home Assistant's `config/custom_components/` directory.
4. Restart Home Assistant.

---

## Setup

1. In Home Assistant, go to Settings > Devices & services.
2. Click Add Integration in the bottom-right corner.
3. Search for GL.iNet and select it.
4. Enter your router URL (default: `http://192.168.8.1`) and admin password.
5. Choose your setup options, including whether you want device tracking, update frequency, and any optional features enabled.

---

## Wiki & Documentation

The main documentation lives in the project [Wiki](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki).

### For End Users
* [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) — What features are supported on each model.
* [Entity Reference](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/entities) — A list of all sensors, switches, and trackers created by the integration.
* [Services & Actions](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/services) — How to call services to control the router (e.g. sending SMS or connecting to repeater WiFi).
* [Automation Templates](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/automations) — Ready-made automations you can import (SMS notifications, etc.).
- [Feature Matrix](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/features) — A quick overview of what the integration supports.
- [Entity Reference](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/entities) — A list of the sensors, switches, buttons, and trackers created by the integration.
- [Services & Actions](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/services) — How to call the router services from Home Assistant.
- [Smart Fan Controls](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/smart-fan) — Fan status, speed, and temperature threshold controls.
- [Unknown Device Management](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/unknown-devices) — Discovery, cleanup, and allow/blocklist handling for unknown devices.

### For Developers
- [Developer Reference](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/developer-reference) — Development setup, tooling, and contribution notes.
- [Architecture](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/architecture) — How the integration is structured.
- [Runtime Hub](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/hub) — Details on the polling and coordinator logic.
- [Router API Details](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/router-api) — Notes on the GL.iNet JSON-RPC API.
- [Modem API](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/modem-api) — Cellular modem API notes.
- [CI & Releases](https://github.com/vithurshanselvarajah/ha-glinet-router/wiki/ci-release) — Testing and release workflows.

<details>
<summary><b>Developer Quick Start</b> (Click to expand)</summary>

### Project Layout
* `custom_components/glinet_router/api`: Bundled GL.iNet API client code.
* `custom_components/glinet_router/entities`: Home Assistant entity implementations.
* `custom_components/glinet_router`: Integration bootstrap, config flow, hub, services, and shared models.
* `docs`: Raw markdown files for the documentation wiki.
* `ha-automations`: Home Assistant automation templates ready to import.
* `tests`: Unit tests with mocked API/session behavior.

### Development Checks
Run the following commands locally to verify code style and tests:
```powershell
py -m pytest -q
ruff check custom_components tests
py -m compileall -q custom_components tests
```
</details>

---

## Support & Contribution

If you find this useful, a star on GitHub is always appreciated.

For support, questions, or general discussion, join the Discord:

[![Discord Banner](https://img.shields.io/badge/Discord-7289DA?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/Metvr5hC3m)

Want to contribute a fix, feature, or docs improvement? See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide. All pull
requests target the `development` branch — PRs opened against
`main` are flagged and will not be merged, except for release PRs
cut by the maintainer team.

### Why I built this
I use this integration at home and wanted something that fit the way I actually use GL.iNet hardware. Over time it grew into a broader setup for router control, monitoring, and automation.

### Special Thanks
- **HarvsG** for the original [glinet-router4-integration](https://github.com/HarvsG/ha-glinet-router4-integration) project which inspired this version.
- **GL.iNet** for their hardware and detailed API documentation.
