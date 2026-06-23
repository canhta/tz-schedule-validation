from __future__ import annotations
import datetime as dt
from dataclasses import dataclass

@dataclass(frozen=True)
class Occurrence:
    date: dt.date
    start: dt.time
    end: dt.time
    teacher: str | None
    teacher_id: int | None
    member: str | None
    member_id: int | None
    group_id: int | None
    location: str | None
    room: str | None
    source: str
    source_id: int | None
    kind: str
    open_ended: bool = False

    def slot_key(self) -> tuple:
        return (self.date, self.start, self.end)

@dataclass(frozen=True)
class Series:
    key: tuple
    dates: frozenset
    start: dt.time
    end: dt.time
    weekday: int
    teacher_id: int | None
    member_id: int | None
    group_id: int | None
    open_ended: bool
    repeat_until: dt.date | None

@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    layer: str
    detail: dict

@dataclass(frozen=True)
class OrgReport:
    org: str
    verdict: str
    summary: dict
    findings: tuple
    coverage: dict
