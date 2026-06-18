from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SEVERITY_ORDER = {"info": 0, "warning": 1, "fail": 2, "rerun_recommended": 3}


@dataclass(frozen=True)
class QCFlag:
    check: str
    severity: str
    message: str
    metric: str | None = None
    value: Any = None

    @property
    def rerun_recommended(self) -> bool:
        return self.severity == "rerun_recommended"


@dataclass
class QCResult:
    run_index: Any = ""
    run_id: str = ""
    file_path: str = ""
    storage_level: str = "failed"
    flags: list[QCFlag] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> str:
        if not self.flags:
            return "pass"
        return max((flag.severity for flag in self.flags), key=lambda item: SEVERITY_ORDER.get(item, 0))

    @property
    def status(self) -> str:
        severity = self.severity
        if severity == "info":
            return "pass"
        return severity

    @property
    def rerun_recommended(self) -> bool:
        return any(flag.severity in {"fail", "rerun_recommended"} for flag in self.flags)

    @property
    def fail_reasons(self) -> list[str]:
        return [flag.message for flag in self.flags if flag.severity in {"fail", "rerun_recommended"}]

    @property
    def warning_reasons(self) -> list[str]:
        return [flag.message for flag in self.flags if flag.severity == "warning"]


def combine_flags(*flag_groups: list[QCFlag]) -> list[QCFlag]:
    flags: list[QCFlag] = []
    for group in flag_groups:
        flags.extend(group)
    return flags
