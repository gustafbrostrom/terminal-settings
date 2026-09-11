"""Battery status via upower (charge thresholds via UPower D-Bus)."""

from __future__ import annotations

from dataclasses import dataclass

from .common import CmdResult, run, which

UPOWER_IFACE = "org.freedesktop.UPower.Device"


@dataclass(frozen=True)
class BatteryInfo:
    available: bool
    percentage: int | None = None
    state: str = "unknown"
    model: str = ""
    technology: str = ""
    energy_wh: float | None = None
    energy_full_wh: float | None = None
    energy_rate_w: float | None = None
    time_to_empty: str = ""
    time_to_full: str = ""
    on_battery: bool = False
    charge_threshold_supported: bool = False
    charge_threshold_enabled: bool = False
    charge_start_threshold: int | None = None
    charge_end_threshold: int | None = None
    device_path: str = ""
    error: str = ""

    @property
    def summary(self) -> str:
        if not self.available:
            return self.error or "No battery"
        pct = f"{self.percentage}%" if self.percentage is not None else "?"
        return f"{pct} | {self.state}"

    @property
    def charging_mode_label(self) -> str:
        if not self.charge_threshold_supported:
            return "unsupported"
        if self.charge_threshold_enabled:
            end = self.charge_end_threshold
            if end is not None:
                return f"preserve health (<={end}%)"
            return "preserve health"
        return "maximize charge"


def _parse_upower(blob: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in blob.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip().lower()] = value.strip()
    return out


def _float_unit(value: str) -> float | None:
    if not value:
        return None
    token = value.split()[0]
    try:
        return float(token)
    except ValueError:
        return None


def _int_pct(value: str) -> int | None:
    if not value:
        return None
    token = value.rstrip("%").split()[0]
    try:
        return int(float(token))
    except ValueError:
        return None


def _yes(value: str) -> bool:
    return value.strip().lower() in {"yes", "true", "1"}


def _find_battery_path() -> tuple[str | None, str]:
    """Return (upower device path, error)."""
    if not which("upower"):
        return None, "upower not installed"

    listed = run("upower", "-e")
    if not listed.ok:
        return None, listed.text or "upower failed"

    battery_path = next(
        (line for line in listed.stdout.splitlines() if "battery_" in line),
        None,
    )
    if battery_path is None:
        display = next(
            (line for line in listed.stdout.splitlines() if line.endswith("DisplayDevice")),
            None,
        )
        battery_path = display

    if battery_path is None:
        return None, "No battery device found"
    return battery_path, ""


def _busctl_get_bool(path: str, prop: str) -> bool | None:
    if not which("busctl"):
        return None
    got = run(
        "busctl",
        "get-property",
        "org.freedesktop.UPower",
        path,
        UPOWER_IFACE,
        prop,
    )
    if not got.ok:
        return None
    # e.g. "b true"
    parts = got.stdout.split()
    if len(parts) >= 2 and parts[0] == "b":
        return parts[1] == "true"
    return None


def get_battery() -> BatteryInfo:
    battery_path, err = _find_battery_path()
    if battery_path is None:
        return BatteryInfo(available=False, error=err)

    detail = run("upower", "-i", battery_path)
    if not detail.ok:
        return BatteryInfo(available=False, error=detail.text or "upower -i failed")

    fields = _parse_upower(detail.stdout)
    pct_raw = fields.get("percentage", "").rstrip("%")
    percentage: int | None
    try:
        percentage = int(float(pct_raw)) if pct_raw else None
    except ValueError:
        percentage = None

    state = fields.get("state", "unknown")
    supported = _yes(fields.get("charge-threshold-supported", ""))
    enabled = _yes(fields.get("charge-threshold-enabled", ""))
    # upower -i omits the enabled line when false; D-Bus is authoritative.
    dbus_enabled = _busctl_get_bool(battery_path, "ChargeThresholdEnabled")
    if dbus_enabled is not None:
        enabled = dbus_enabled

    return BatteryInfo(
        available=True,
        percentage=percentage,
        state=state,
        model=fields.get("model", ""),
        technology=fields.get("technology", ""),
        energy_wh=_float_unit(fields.get("energy", "")),
        energy_full_wh=_float_unit(fields.get("energy-full", "")),
        energy_rate_w=_float_unit(fields.get("energy-rate", "")),
        time_to_empty=fields.get("time to empty", ""),
        time_to_full=fields.get("time to full", ""),
        on_battery=state.lower() == "discharging",
        charge_threshold_supported=supported,
        charge_threshold_enabled=enabled if supported else False,
        charge_start_threshold=_int_pct(fields.get("charge-start-threshold", "")),
        charge_end_threshold=_int_pct(fields.get("charge-end-threshold", "")),
        device_path=battery_path,
    )


def set_charge_threshold_enabled(enabled: bool) -> CmdResult:
    """Toggle preserve-battery-health via UPower EnableChargeThreshold."""
    if not which("busctl"):
        return CmdResult(False, "", "busctl not installed", 127)

    battery_path, err = _find_battery_path()
    if battery_path is None:
        return CmdResult(False, "", err or "No battery", 1)

    supported = _busctl_get_bool(battery_path, "ChargeThresholdSupported")
    if supported is False:
        return CmdResult(
            False,
            "",
            "Charge thresholds not supported on this hardware",
            1,
        )

    return run(
        "busctl",
        "call",
        "org.freedesktop.UPower",
        battery_path,
        UPOWER_IFACE,
        "EnableChargeThreshold",
        "b",
        "true" if enabled else "false",
    )
