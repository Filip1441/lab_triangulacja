import re
import subprocess

from PySide6.QtCore import QThread, Signal

NM = ["sudo", "-n", "nmcli"]
PROFILE_PREFIX = "lab-wifi-"      # profiles added from the admin window
PROTECTED = ("LabPi-Hotspot",)    # never offered for deletion


def _run(args, timeout=60):
    p = subprocess.run(NM + args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _split(line):
    """Splits nmcli -t output on unescaped colons."""
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]


def current():
    """Name of the active Wi-Fi connection, or ''."""
    rc, out = _run(["-t", "-f", "TYPE,NAME", "connection", "show", "--active"], 10)
    for line in out.splitlines():
        t, _, name = line.partition(":")
        if t == "802-11-wireless":
            return name
    return ""


def scan():
    """Visible networks as [(ssid, signal, secured)], strongest first, duplicates merged."""
    rc, out = _run(["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"], 30)
    best = {}
    for line in out.splitlines():
        f = _split(line)
        if len(f) < 3 or not f[0]:
            continue
        sig = int(f[1]) if f[1].isdigit() else 0
        if f[0] not in best or sig > best[f[0]][0]:
            best[f[0]] = (sig, bool(f[2].strip()))
    return sorted(((s, v[0], v[1]) for s, v in best.items()), key=lambda x: -x[1])


def saved():
    """Saved Wi-Fi profiles that may be removed (everything except the lab hotspot)."""
    rc, out = _run(["-t", "-f", "NAME,TYPE", "connection", "show"], 10)
    names = []
    for line in out.splitlines():
        f = _split(line)
        if len(f) >= 2 and f[1] == "802-11-wireless" and f[0] not in PROTECTED:
            names.append(f[0])
    return names


def connect(ssid, password):
    """Saves the network (reconnects automatically later) and connects now. Returns (ok, message)."""
    ssid = ssid.strip()
    if not ssid:
        return False, "Enter the network name."
    name = PROFILE_PREFIX + ssid
    _run(["connection", "delete", name], 10)   # replace an older profile of the same network
    args = ["connection", "add", "type", "wifi", "con-name", name, "ifname", "wlan0", "ssid", ssid,
            "connection.autoconnect", "yes", "connection.autoconnect-priority", "10"]
    if password:
        args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    rc, out = _run(args, 15)
    if rc != 0:
        return False, out.strip().splitlines()[-1] if out.strip() else "Could not save the network."
    rc, out = _run(["--wait", "30", "connection", "up", name], 45)
    if rc != 0:
        _run(["connection", "delete", name], 10)
        return False, "Could not connect (wrong password or out of range)."
    return True, f"Connected to {ssid}."


def forget(name):
    rc, out = _run(["connection", "delete", name], 10)
    return rc == 0


class Job(QThread):
    """Runs a blocking function off the GUI thread and reports its result."""
    done = Signal(object)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(self.fn(*self.args))
        except Exception as e:
            self.done.emit(e)
