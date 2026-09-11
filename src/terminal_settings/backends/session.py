"""Sleep, hibernate, lock, reboot, shutdown."""

from __future__ import annotations

from .common import CmdResult, run, which


def can_suspend() -> bool:
    return which("systemctl") is not None


def suspend() -> CmdResult:
    return run("systemctl", "suspend")


def hibernate() -> CmdResult:
    return run("systemctl", "hibernate")


def hybrid_sleep() -> CmdResult:
    return run("systemctl", "hybrid-sleep")


def lock_session() -> CmdResult:
    if which("loginctl"):
        return run("loginctl", "lock-session")
    return CmdResult(False, "", "loginctl not available", 1)


def reboot() -> CmdResult:
    return run("systemctl", "reboot")


def poweroff() -> CmdResult:
    return run("systemctl", "poweroff")
