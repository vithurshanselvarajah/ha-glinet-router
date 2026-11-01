DOMAIN = "glinet_router"
API_PATH = "/rpc"
INTEGRATION_NAME = "GL.iNet Router"
DEFAULT_URL = "http://192.168.8.1"
DEFAULT_USERNAME = "root"
DEFAULT_PASSWORD = "ChangeMe!"
CONF_TITLE = "title"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLED_FEATURES = "enabled_features"
CONF_ADD_ALL_DEVICES = "add_all_devices"
CONF_CLEANUP_DEVICES = "cleanup_devices"
CONF_WAN_STATUS_MONITORS = "wan_status_monitors"
CONF_UNKNOWN_DEVICES_FILTER_MODE = "unknown_devices_filter_mode"
CONF_UNKNOWN_DEVICES_FILTER_SELECT = "unknown_devices_filter_select"
CONF_UNKNOWN_DEVICES_FILTER_MANUAL = "unknown_devices_filter_manual"
CONF_VERIFY_SSL = "verify_ssl"
CONF_PARALLEL_REQUESTS = "parallel_requests"
DEFAULT_PARALLEL_REQUESTS = False
DEFAULT_UNKNOWN_DEVICES_FILTER_MODE = "blacklist"

WAN_INTERFACE_NAMES = {
    "wan": "Ethernet 1",
    "wwan": "Repeater",
    "tethering": "Tethering",
    "modem_0001": "Cellular",
    "modem_0001_s1": "Cellular SIM 1",
    "modem_0001_s2": "Cellular SIM 2",
    "secondwan": "Ethernet 2",
}

FEATURE_CELLULAR = "cellular"
FEATURE_REPEATER = "repeater"
FEATURE_SMS = "sms"
FEATURE_TAILSCALE = "tailscale"
FEATURE_WG_CLIENT = "wg_client"
FEATURE_WG_SERVER = "wg_server"
FEATURE_OVPN_CLIENT = "ovpn_client"
FEATURE_OVPN_SERVER = "ovpn_server"
FEATURE_ZEROTIER = "zerotier"
FEATURE_KMWAN = "kmwan"
FEATURE_MWAN3 = "mwan3"
FEATURE_ADGUARD = "adguard"
FEATURE_LED = "led"
FEATURE_FIREWALL = "firewall"
FEATURE_MCU_BATTERY = "mcu_battery"
FEATURE_MCU_OLED = "mcu_oled"
FEATURE_PARENTAL_CONTROL = "parental_control"
FEATURE_PLAYGROUND = "playground"
FEATURE_OPTIONS = [
    FEATURE_CELLULAR,
    FEATURE_REPEATER,
    FEATURE_SMS,
    FEATURE_TAILSCALE,
    FEATURE_WG_CLIENT,
    FEATURE_WG_SERVER,
    FEATURE_OVPN_CLIENT,
    FEATURE_OVPN_SERVER,
    FEATURE_ZEROTIER,
    FEATURE_FIREWALL,
    FEATURE_MCU_BATTERY,
    FEATURE_MCU_OLED,
    FEATURE_PARENTAL_CONTROL,
    FEATURE_PLAYGROUND,
]

# Legacy cellular sensors that were dropped in v1.6.1. Firmware 4.9 stopped
# reporting the underlying values, but firmware 4.8 still provides them, so
# these sensors stay registered on 4.8 only. Keeping the list in one place
# makes the registration gate and the entity-registry cleanup agree.
LEGACY_CELLULAR_SENSOR_KEYS = frozenset({"cellular_signal", "cellular_rssi", "cellular_network"})


SERVICE_GET_SMS = "get_sms"
SERVICE_REMOVE_SMS = "remove_sms"
SERVICE_REFRESH_SMS = "refresh_sms"
SERVICE_SEND_SMS = "send_sms"
SERVICE_REFRESH_CLIENTS = "refresh_clients"

SERVICE_SCAN_WIFI = "scan_wifi"
SERVICE_CONNECT_WIFI = "connect_wifi"
SERVICE_DISCONNECT_WIFI = "disconnect_wifi"
SERVICE_GET_SAVED_NETWORKS = "get_saved_networks"
SERVICE_REMOVE_SAVED_NETWORK = "remove_saved_network"
SERVICE_SET_FAN_TEMPERATURE = "set_fan_temperature"

SERVICE_ADD_FIREWALL_RULE = "add_firewall_rule"
SERVICE_GET_FIREWALL_RULES = "get_firewall_rules"
SERVICE_REMOVE_FIREWALL_RULE = "remove_firewall_rule"
SERVICE_ADD_PORT_FORWARD = "add_port_forward"
SERVICE_REMOVE_PORT_FORWARD = "remove_port_forward"
SERVICE_SET_DMZ = "set_dmz"
SERVICE_GET_MCU_BATTERY_CONFIG = "get_mcu_battery_config"
SERVICE_SET_MCU_BATTERY_CONFIG = "set_mcu_battery_config"
SERVICE_GET_MCU_OLED_CONFIG = "get_mcu_oled_config"
SERVICE_SET_MCU_OLED_CONFIG = "set_mcu_oled_config"
SERVICE_PARENTAL_CONTROL_SET_TEMPORARY_OVERRIDE = "parental_control_set_temporary_override"
SERVICE_PARENTAL_CONTROL_SET_FILTERING_MODE = "parental_control_set_filtering_mode"
SERVICE_PARENTAL_CONTROL_UPDATE_SIGNATURES = "parental_control_update_signatures"
SERVICE_ACCESS_CONTROL_SET_MODE = "access_control_set_mode"
SERVICE_ACCESS_CONTROL_SET_DEVICE_BLOCK = "access_control_set_device_block"
SERVICE_PARENTAL_CONTROL_SET_GROUP_SCHEDULES = "parental_control_set_group_schedules"
SERVICE_PLAYGROUND = "playground"
SERVICE_KMWAN_GET_CONFIG = "kmwan_get_config"
SERVICE_KMWAN_GET_STATUS = "kmwan_get_status"
SERVICE_KMWAN_SET_CONFIG = "kmwan_set_config"
SERVICE_KMWAN_SET_INTERFACE = "kmwan_set_interface"
SERVICE_KMWAN_SET_SENSITIVITY = "kmwan_set_sensitivity"
SERVICE_MWAN3_GET_CONFIG = "mwan3_get_config"
SERVICE_MWAN3_GET_STATUS = "mwan3_get_status"
SERVICE_MWAN3_SET_CONFIG = "mwan3_set_config"
SERVICE_MWAN3_SET_INTERFACE = "mwan3_set_interface"

ATTR_MESSAGE_ID = "message_id"
ATTR_SCOPE = "scope"
ATTR_METHOD = "method"
ATTR_BODY = "body"
ATTR_RECIPIENT = "recipient"
ATTR_TEXT = "text"

ATTR_SSID = "ssid"
ATTR_PASSWORD = "password"
ATTR_REMEMBER = "remember"
ATTR_BSSID = "bssid"
ATTR_ALL_BAND = "all_band"
ATTR_DFS = "dfs"
ATTR_REFRESH = "refresh"
ATTR_TEMPERATURE = "temperature"

ATTR_ENABLED = "enabled"
ATTR_DEST_IP = "dest_ip"
ATTR_RULE_ID = "rule_id"
ATTR_REMOVE_ALL = "remove_all"
ATTR_CAPACITY = "capacity"
ATTR_CAPACITY_ENABLED = "capacity_enabled"
ATTR_TEMP_HIGH = "temp_high"
ATTR_TEMP_HIGH_ENABLED = "temp_high_enabled"
ATTR_TEMP_LOW = "temp_low"
ATTR_TEMP_LOW_ENABLED = "temp_low_enabled"
ATTR_MAIN = "main"
ATTR_WIFI_PASSWORD = "wifi_password"
ATTR_WIFI_2G = "wifi_2g"
ATTR_WIFI_5G = "wifi_5g"
ATTR_LAN = "lan"
ATTR_VPN = "vpn"
ATTR_CUSTOM = "custom"
ATTR_CONTENT = "content"
ATTR_SRC = "src"
ATTR_SRC_IP = "src_ip"
ATTR_SRC_MAC = "src_mac"
ATTR_SRC_PORT = "src_port"
ATTR_PROTO = "proto"
ATTR_DEST = "dest"
ATTR_DEST_PORT = "dest_port"
ATTR_TARGET = "target"
ATTR_SRC_DPORT = "src_dport"
ATTR_NAME = "name"
ATTR_GROUP = "group"
ATTR_GROUP_ID = "group_id"
ATTR_DURATION = "duration"
ATTR_MODE = "mode"
ATTR_BLOCK = "block"
ATTR_CONFIG = "config"
ATTR_INTERFACE = "interface"
ATTR_SENSITIVITY = "sensitivity"
ATTR_LEVEL = "level"
ATTR_VAL = "val"
