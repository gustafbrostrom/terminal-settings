"""VPN / WireGuard control via NetworkManager (nmcli)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .common import CmdResult, run, which

# NetworkManager connection types that GNOME Settings groups under VPN.
VPN_TYPES = frozenset({"vpn", "wireguard"})

_SERVICE_LABELS = {
    "org.freedesktop.NetworkManager.openvpn": "OpenVPN",
    "org.freedesktop.NetworkManager.strongswan": "IPsec",
    "org.freedesktop.NetworkManager.vpnc": "Cisco VPNC",
    "org.freedesktop.NetworkManager.pptp": "PPTP",
    "org.freedesktop.NetworkManager.l2tp": "L2TP",
    "org.freedesktop.NetworkManager.openconnect": "OpenConnect",
    "org.freedesktop.NetworkManager.libreswan": "Libreswan",
}


@dataclass(frozen=True)
class VpnConnection:
    name: str
    conn_type: str  # vpn | wireguard
    service: str  # vpn plugin D-Bus name, or "" for wireguard
    active: bool
    device: str = ""

    @property
    def type_label(self) -> str:
        if self.conn_type == "wireguard":
            return "WireGuard"
        return _SERVICE_LABELS.get(self.service, "VPN")


@dataclass(frozen=True)
class VpnStatus:
    available: bool
    active_names: tuple[str, ...] = ()
    error: str = ""

    @property
    def summary(self) -> str:
        if not self.available:
            return self.error or "n/a"
        if self.active_names:
            return ", ".join(self.active_names)
        return "not connected"


def _nmcli(*args: str, timeout: float = 45.0) -> CmdResult:
    return run("nmcli", "-t", *args, timeout=timeout)


def get_vpn_status() -> VpnStatus:
    if not which("nmcli"):
        return VpnStatus(available=False, error="nmcli not installed")

    active = _nmcli("-f", "NAME,TYPE,DEVICE", "connection", "show", "--active")
    if not active.ok:
        return VpnStatus(available=True, error=active.text or "nmcli failed")

    names: list[str] = []
    for line in active.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        name, conn_type = parts[0], parts[1]
        if conn_type in VPN_TYPES:
            names.append(name)
    return VpnStatus(available=True, active_names=tuple(names))


def list_vpn() -> tuple[list[VpnConnection], str]:
    """Return saved VPN and WireGuard profiles."""
    status = get_vpn_status()
    if not status.available:
        return [], status.error

    listed = _nmcli("-f", "NAME,TYPE,DEVICE", "connection", "show")
    if not listed.ok:
        return [], listed.text or "connection show failed"

    active_names = set(status.active_names)
    connections: list[VpnConnection] = []
    for line in listed.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        name, conn_type = parts[0], parts[1]
        if conn_type not in VPN_TYPES:
            continue
        device = parts[2] if len(parts) > 2 else ""
        service = ""
        if conn_type == "vpn":
            got = run("nmcli", "-g", "vpn.service-type", "connection", "show", name)
            if got.ok:
                service = got.stdout
        connections.append(
            VpnConnection(
                name=name,
                conn_type=conn_type,
                service=service,
                active=name in active_names,
                device=device,
            )
        )

    connections.sort(key=lambda c: (not c.active, c.name.lower()))
    return connections, ""


def connect_vpn(name: str) -> CmdResult:
    return run("nmcli", "connection", "up", "id", name, timeout=90)


def disconnect_vpn(name: str) -> CmdResult:
    return run("nmcli", "connection", "down", "id", name, timeout=60)


def disconnect_active_vpns() -> CmdResult:
    """Bring down all active VPN/WireGuard connections."""
    status = get_vpn_status()
    if not status.available:
        return CmdResult(False, "", status.error or "nmcli unavailable", 1)
    if not status.active_names:
        return CmdResult(False, "", "No VPN connected", 1)

    last = CmdResult(False, "", "No VPN connected", 1)
    for name in status.active_names:
        last = disconnect_vpn(name)
        if not last.ok:
            return last
    return last


def guess_import_type(path: str | Path) -> str | None:
    """Guess nmcli import type from file extension."""
    suffix = Path(path).suffix.lower()
    if suffix == ".ovpn":
        return "openvpn"
    if suffix == ".conf":
        return "wireguard"
    return None


def import_vpn(path: str | Path, *, import_type: str | None = None) -> CmdResult:
    """Import an OpenVPN (.ovpn) or WireGuard (.conf) profile into NetworkManager."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        return CmdResult(False, "", f"File not found: {file_path}", 1)

    kind = import_type or guess_import_type(file_path)
    if not kind:
        return CmdResult(
            False,
            "",
            "Unknown config type — use .ovpn (OpenVPN) or .conf (WireGuard)",
            1,
        )

    return run(
        "nmcli",
        "connection",
        "import",
        "type",
        kind,
        "file",
        str(file_path),
        timeout=60,
    )
