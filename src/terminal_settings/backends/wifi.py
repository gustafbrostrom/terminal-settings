"""Wi-Fi control via NetworkManager (nmcli)."""

from __future__ import annotations

from dataclasses import dataclass

from .common import CmdResult, run, which


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int
    security: str
    in_use: bool
    bssid: str = ""


@dataclass(frozen=True)
class WifiStatus:
    available: bool
    radio_on: bool = False
    connected_ssid: str = ""
    device: str = ""
    error: str = ""


def _nmcli(*args: str, timeout: float = 45.0) -> CmdResult:
    return run("nmcli", "-t", *args, timeout=timeout)


def get_wifi_status() -> WifiStatus:
    if not which("nmcli"):
        return WifiStatus(available=False, error="nmcli not installed")

    radio = run("nmcli", "-t", "radio", "wifi")
    radio_on = radio.ok and radio.stdout.strip().lower() == "enabled"

    device = ""
    connected_ssid = ""
    devices = _nmcli("-f", "DEVICE,TYPE,STATE", "device", "status")
    if devices.ok:
        for line in devices.stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 3:
                continue
            if parts[1] == "wifi":
                device = parts[0]
                if "connected" in parts[2] and "externally" not in parts[2]:
                    break

    active = _nmcli("-f", "NAME,TYPE,DEVICE", "connection", "show", "--active")
    if active.ok:
        for line in active.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and "wireless" in parts[1]:
                connected_ssid = parts[0]
                if len(parts) >= 3 and parts[2]:
                    device = parts[2] or device
                break

    return WifiStatus(
        available=True,
        radio_on=radio_on,
        connected_ssid=connected_ssid,
        device=device,
    )


def set_wifi_radio(enabled: bool) -> CmdResult:
    return run("nmcli", "radio", "wifi", "on" if enabled else "off")


def list_wifi(*, rescan: bool = False) -> tuple[list[WifiNetwork], str]:
    """Return known/visible networks. Only triggers an active RF scan when rescan=True."""
    status = get_wifi_status()
    if not status.available:
        return [], status.error
    if not status.radio_on:
        return [], "Wi-Fi radio is off"

    listed = _nmcli(
        "-f",
        "SSID,SIGNAL,SECURITY,IN-USE,BSSID",
        "device",
        "wifi",
        "list",
        "--rescan",
        "yes" if rescan else "no",
        timeout=45 if rescan else 15,
    )
    if not listed.ok:
        # Older nmcli may not support --rescan on list; fall back without forcing a scan.
        listed = _nmcli(
            "-f",
            "SSID,SIGNAL,SECURITY,IN-USE,BSSID",
            "device",
            "wifi",
            "list",
            timeout=30,
        )
    if not listed.ok:
        return [], listed.text or "wifi list failed"

    networks: list[WifiNetwork] = []
    seen: set[str] = set()
    for line in listed.stdout.splitlines():
        # BSSID contains colons; nmcli -t escapes : as \:
        parts = _split_nmcli(line)
        if len(parts) < 4:
            continue
        ssid, signal_s, security, in_use = parts[0], parts[1], parts[2], parts[3]
        bssid = parts[4] if len(parts) > 4 else ""
        if not ssid:
            continue
        try:
            signal = int(signal_s)
        except ValueError:
            signal = 0
        if not security or security in {"--", "-"}:
            security = "Open"
        key = ssid
        # Prefer strongest / in-use entry per SSID.
        if key in seen:
            existing = next(n for n in networks if n.ssid == key)
            if in_use == "*" or signal > existing.signal:
                networks.remove(existing)
            else:
                continue
        seen.add(key)
        networks.append(
            WifiNetwork(
                ssid=ssid,
                signal=signal,
                security=security,
                in_use=in_use == "*",
                bssid=bssid,
            )
        )

    networks.sort(key=lambda n: (not n.in_use, -n.signal, n.ssid.lower()))
    return networks, ""


def _split_nmcli(line: str) -> list[str]:
    """Split nmcli -t output, respecting \\: escapes."""
    parts: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def find_saved_wifi(ssid: str) -> str | None:
    """Return NetworkManager connection id for this SSID, if one exists."""
    listed = _nmcli("-f", "NAME,TYPE", "connection", "show")
    if not listed.ok:
        return None

    candidates: list[str] = []
    for line in listed.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        name, conn_type = parts[0], parts[1]
        if conn_type != "802-11-wireless":
            continue
        if name == ssid:
            return name
        candidates.append(name)

    for name in candidates:
        got = run("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name)
        if got.ok and got.stdout == ssid:
            return name
    return None


def list_saved_wifi_ssids() -> set[str]:
    """SSIDs that already have a NetworkManager profile (secrets may be stored)."""
    listed = _nmcli("-f", "NAME,TYPE", "connection", "show")
    if not listed.ok:
        return set()

    ssids: set[str] = set()
    for line in listed.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2 or parts[1] != "802-11-wireless":
            continue
        name = parts[0]
        got = run("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name)
        ssid = got.stdout if got.ok and got.stdout else name
        if ssid:
            ssids.add(ssid)
    return ssids


def connect_wifi(ssid: str, password: str | None = None) -> CmdResult:
    """Activate Wi-Fi. Prefer a saved profile; only pass password for new joins."""
    saved = find_saved_wifi(ssid)

    if saved and not password:
        return run("nmcli", "connection", "up", "id", saved, timeout=60)

    if password:
        # New network, or re-join with an explicit password.
        result = run(
            "nmcli",
            "device",
            "wifi",
            "connect",
            ssid,
            "password",
            password,
            timeout=60,
        )
        if result.ok:
            return result
        # If a profile already exists, update its PSK then activate it.
        if saved:
            updated = run(
                "nmcli",
                "connection",
                "modify",
                "id",
                saved,
                "wifi-sec.psk",
                password,
            )
            if not updated.ok:
                return result
            return run("nmcli", "connection", "up", "id", saved, timeout=60)
        return result

    return run("nmcli", "device", "wifi", "connect", ssid, timeout=60)


def disconnect_wifi() -> CmdResult:
    status = get_wifi_status()
    if not status.device:
        return CmdResult(False, "", "No Wi-Fi device", 1)
    return run("nmcli", "device", "disconnect", status.device)
