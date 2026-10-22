import re
import subprocess

import config

HOTSPOT_CONNECTION = "LabPi-Hotspot"


def _run(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=4).strip()
    except Exception:
        return ""


def _wifi_escape(s):
    return re.sub(r'([\;,:"])', r'\\\1', s)


def get_share_info():
    """
    Returns {"mode": "hotspot"|"client"|"unknown", "ssid", "password", "ip", "url", "wifi_qr"}.
    In hotspot mode wifi_qr lets a phone join the Pi's network; in client mode only the URL is meaningful.
    """
    port = getattr(config, 'SHARE_PORT', 8000)
    conn = ""
    for line in _run(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "dev"]).splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[0] == "wlan0" and parts[1] == "connected":
            conn = parts[2]
    ip = ""
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", _run(["ip", "-4", "-o", "addr", "show", "wlan0"]))
    if m:
        ip = m.group(1)
    if not ip:
        ip = (_run(["hostname", "-I"]).split() or ["localhost"])[0]

    info = {"mode": "unknown", "ssid": "", "password": "", "ip": ip, "wifi_qr": None}
    if conn == HOTSPOT_CONNECTION:
        info["mode"] = "hotspot"
        info["ssid"] = _run(["nmcli", "-g", "802-11-wireless.ssid", "con", "show", conn])
        pw = _run(["nmcli", "-s", "-g", "802-11-wireless-security.psk", "con", "show", conn])
        if not pw:
            pw = _run(["sudo", "-n", "nmcli", "-s", "-g", "802-11-wireless-security.psk", "con", "show", conn])
        info["password"] = pw
        if info["ssid"]:
            sec = "WPA" if pw else "nopass"
            info["wifi_qr"] = f"WIFI:T:{sec};S:{_wifi_escape(info['ssid'])};" + \
                              (f"P:{_wifi_escape(pw)};" if pw else "") + ";"
    elif conn:
        info["mode"] = "client"
        info["ssid"] = conn
    info["url"] = f"http://{ip}:{port}/"
    return info
