"""Helpers for calling host system tools."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CmdResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int

    @property
    def text(self) -> str:
        return self.stdout if self.ok else (self.stderr or self.stdout)


def which(name: str) -> str | None:
    return shutil.which(name)


def run(
    *args: str,
    timeout: float = 30.0,
    input_text: str | None = None,
) -> CmdResult:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            check=False,
        )
    except FileNotFoundError:
        return CmdResult(False, "", f"{args[0]} not found", 127)
    except subprocess.TimeoutExpired:
        return CmdResult(False, "", f"timed out: {' '.join(args)}", 124)

    return CmdResult(
        ok=completed.returncode == 0,
        stdout=(completed.stdout or "").strip(),
        stderr=(completed.stderr or "").strip(),
        returncode=completed.returncode,
    )
