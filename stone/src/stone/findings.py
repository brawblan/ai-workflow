"""Shared finding type and output formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    check: str
    message: str
    severity: Severity = "error"

    def as_text(self) -> str:
        return f"{self.path}:{self.line}: {self.severity}: {self.check}: {self.message}"

    def as_github(self, force_warning: bool = False) -> str:
        level = "warning" if force_warning or self.severity == "warning" else "error"
        message = self.message.replace("%", "%25").replace("\n", "%0A")
        return f"::{level} file={self.path},line={self.line},title={self.check}::{message}"


def report(findings: Iterable[Finding], fmt: str, warn_only: bool = False) -> int:
    """Print the findings. Return the number of findings that block."""
    blocking = 0
    for finding in sorted(findings, key=lambda f: (f.path, f.line, f.check)):
        if fmt == "github":
            print(finding.as_github(force_warning=warn_only))
        else:
            print(finding.as_text())
        if finding.severity == "error" and not warn_only:
            blocking += 1
    return blocking
