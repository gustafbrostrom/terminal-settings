"""Bluetooth control via bluetoothctl / rfkill."""

from __future__ import annotations

from dataclasses import dataclass

from .common import CmdResult, run, which


@dataclass(frozen=True)
class BtDevice:
    address: str
    name: str
    connected: bool = False
    paired: bool = False


@dataclass(frozen=True)
class BluetoothStatus:
    available: bool
    powered: bool = False
    discoverable: bool = False
    pairable: bool = False
    adapter_name: str = ""
    error: str = ""


def _bt(*args: str, timeout: float = 20.0) -> CmdResult:
    return run("bluetoothctl", *args, timeout=timeout)


def get_bluetooth_status() -> BluetoothStatus:
    if not which("bluetoothctl"):
        return BluetoothStatus(available=False, error="bluetoothctl not installed")

    shown = _bt("show")
    if not shown.ok:
        return BluetoothStatus(available=False, error=shown.text or "no adapter")

    powered = False
    discoverable = False
    pairable = False
    name = ""
    for line in shown.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Powered:"):
            powered = stripped.split(":", 1)[1].strip().lower() == "yes"
        elif stripped.startswith("Discoverable:"):
            discoverable = stripped.split(":", 1)[1].strip().lower() == "yes"
        elif stripped.startswith("Pairable:"):
            pairable = stripped.split(":", 1)[1].strip().lower() == "yes"
        elif stripped.startswith("Name:"):
            name = stripped.split(":", 1)[1].strip()

    return BluetoothStatus(
        available=True,
        powered=powered,
        discoverable=discoverable,
        pairable=pairable,
        adapter_name=name,
    )


def set_bluetooth_powered(enabled: bool) -> CmdResult:
    return _bt("power", "on" if enabled else "off")


def set_discoverable(enabled: bool) -> CmdResult:
    return _bt("discoverable", "on" if enabled else "off")


def list_devices() -> tuple[list[BtDevice], str]:
    status = get_bluetooth_status()
    if not status.available:
        return [], status.error

    paired = _bt("devices", "Paired")
    connected = _bt("devices", "Connected")
    all_devs = _bt("devices")

    connected_addrs = set()
    if connected.ok:
        for line in connected.stdout.splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                connected_addrs.add(parts[1])

    paired_addrs = set()
    if paired.ok:
        for line in paired.stdout.splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                paired_addrs.add(parts[1])

    devices: list[BtDevice] = []
    seen: set[str] = set()
    source = all_devs.stdout if all_devs.ok else ""
    if paired.ok and paired.stdout:
        source = "\n".join(filter(None, [source, paired.stdout]))

    for line in source.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) < 2 or parts[0] != "Device":
            continue
        address = parts[1]
        if address in seen:
            continue
        seen.add(address)
        name = parts[2] if len(parts) > 2 else address
        devices.append(
            BtDevice(
                address=address,
                name=name,
                connected=address in connected_addrs,
                paired=address in paired_addrs,
            )
        )

    devices.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
    return devices, ""


def scan_devices(duration: float = 8.0) -> CmdResult:
    # bluetoothctl scan on/off; use a timed scan via timeout wrapper.
    return run(
        "bash",
        "-c",
        f"bluetoothctl --timeout {int(duration)} scan on",
        timeout=duration + 5,
    )


def connect_device(address: str) -> CmdResult:
    return _bt("connect", address, timeout=40)


def disconnect_device(address: str) -> CmdResult:
    return _bt("disconnect", address, timeout=20)


def trust_and_pair(address: str) -> CmdResult:
    run_pair = _bt("pair", address, timeout=40)
    if not run_pair.ok:
        return run_pair
    _bt("trust", address)
    return _bt("connect", address, timeout=40)
