"""CPU / package temperature via sysfs thermal zones and hwmon."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

THERMAL_ROOT = Path("/sys/class/thermal")
HWMON_ROOT = Path("/sys/class/hwmon")

# Prefer package/CPU sensors in this order.
PREFERRED_ZONE_TYPES = (
    "x86_pkg_temp",
    "TCPU",
    "cpu-thermal",
    "soc_thermal",
    "acpitz",
)

PREFERRED_HWMON = ("coretemp", "k10temp", "zenpower", "cpu_thermal")


@dataclass(frozen=True)
class TemperatureInfo:
    available: bool
    celsius: float | None = None
    source: str = ""
    error: str = ""

    @property
    def summary(self) -> str:
        if not self.available or self.celsius is None:
            return self.error or "n/a"
        return f"{self.celsius:.0f}°C"


def _read_millidegrees(path: Path) -> float | None:
    try:
        raw = path.read_text().strip()
        return int(raw) / 1000.0
    except (OSError, ValueError):
        return None


def _from_thermal_zones() -> TemperatureInfo | None:
    if not THERMAL_ROOT.is_dir():
        return None

    zones: dict[str, float] = {}
    for zone in sorted(THERMAL_ROOT.glob("thermal_zone*")):
        type_path = zone / "type"
        temp_path = zone / "temp"
        if not type_path.is_file() or not temp_path.is_file():
            continue
        try:
            ztype = type_path.read_text().strip()
        except OSError:
            continue
        celsius = _read_millidegrees(temp_path)
        if celsius is None:
            continue
        zones[ztype] = celsius

    if not zones:
        return None

    for preferred in PREFERRED_ZONE_TYPES:
        if preferred in zones:
            return TemperatureInfo(
                available=True, celsius=zones[preferred], source=preferred
            )

    # Fall back to the hottest non-wifi zone, else any zone.
    skip = {"iwlwifi_1", "INT3400 Thermal"}
    candidates = {k: v for k, v in zones.items() if k not in skip} or zones
    source, celsius = max(candidates.items(), key=lambda item: item[1])
    return TemperatureInfo(available=True, celsius=celsius, source=source)


def _from_hwmon() -> TemperatureInfo | None:
    if not HWMON_ROOT.is_dir():
        return None

    by_name: dict[str, list[float]] = {}
    for hwmon in sorted(HWMON_ROOT.glob("hwmon*")):
        name_path = hwmon / "name"
        if not name_path.is_file():
            continue
        try:
            name = name_path.read_text().strip()
        except OSError:
            continue
        readings: list[float] = []
        for temp_input in sorted(hwmon.glob("temp*_input")):
            celsius = _read_millidegrees(temp_input)
            if celsius is not None:
                readings.append(celsius)
        if readings:
            by_name[name] = readings

    if not by_name:
        return None

    for preferred in PREFERRED_HWMON:
        if preferred in by_name:
            # Package/die temp is usually temp1 on coretemp/k10temp.
            return TemperatureInfo(
                available=True,
                celsius=by_name[preferred][0],
                source=preferred,
            )

    name, readings = next(iter(by_name.items()))
    return TemperatureInfo(available=True, celsius=readings[0], source=name)


def get_temperature() -> TemperatureInfo:
    info = _from_thermal_zones()
    if info is not None:
        return info
    info = _from_hwmon()
    if info is not None:
        return info
    return TemperatureInfo(available=False, error="No thermal sensor found")
