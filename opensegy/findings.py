"""What the reader noticed, and how much it matters.

One shape, used by every stage. The rule that makes it worth having is the one
the platform learned the expensive way: a finding that cannot name the bytes it
came from is an opinion, and opinions do not survive a disagreement with a
processor six months later.

Severity is deliberately coarse:

    ERROR    the file cannot be read correctly as it stands
    WARNING  it can be read, but something here will mislead someone
    INFO     worth stating; nothing is wrong

There is no "critical" and no numeric score. Three levels force the question
"would this stop a load?" to have an answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    #: Stable machine key, e.g. "revision.declared_conflicts_with_structure".
    #: Callers filter and suppress on this, so it must not change casually.
    code: str
    #: One sentence, written for a geoscientist, not a parser author.
    message: str
    byte_range: tuple[int, int] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "byte_range": list(self.byte_range) if self.byte_range else None,
            "evidence": self.evidence,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.severity.value.upper()} {self.code}: {self.message}>"


def error(code: str, message: str, **kw) -> Finding:
    return Finding(Severity.ERROR, code, message, **kw)


def warning(code: str, message: str, **kw) -> Finding:
    return Finding(Severity.WARNING, code, message, **kw)


def info(code: str, message: str, **kw) -> Finding:
    return Finding(Severity.INFO, code, message, **kw)


def worst(findings: list[Finding]) -> Severity | None:
    """The highest severity present, or None for a clean read."""
    for level in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        if any(f.severity is level for f in findings):
            return level
    return None
