"""Power profiles via powerprofilesctl."""

from __future__ import annotations

from dataclasses import dataclass

from .common import CmdResult, run, which


PROFILES = ("power-saver", "balanced", "performance")


@dataclass(frozen=True)
class PowerStatus:
    available: bool
    active: str = ""
    profiles: tuple[str, ...] = ()
    error: str = ""


def get_power_status() -> PowerStatus:
    if not which("powerprofilesctl"):
        return PowerStatus(available=False, error="powerprofilesctl not installed")

    listed = run("powerprofilesctl", "list")
    if not listed.ok:
        return PowerStatus(available=False, error=listed.text or "list failed")

    profiles: list[str] = []
    active = ""
    for line in listed.stdout.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        name = stripped.split(":", 1)[0].strip()
        if name.startswith("*"):
            name = name.lstrip("*").strip()
            active = name
        if name in PROFILES or name.replace(" ", "-") in PROFILES:
            profiles.append(name)

    if not profiles:
        profiles = list(PROFILES)

    if not active:
        got = run("powerprofilesctl", "get")
        active = got.stdout if got.ok else ""

    return PowerStatus(available=True, active=active, profiles=tuple(profiles))


def set_power_profile(profile: str) -> CmdResult:
    return run("powerprofilesctl", "set", profile)
