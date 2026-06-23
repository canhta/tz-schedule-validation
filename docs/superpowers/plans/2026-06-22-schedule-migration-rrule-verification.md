# Schedule Migration RRULE Verification Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent, black-box Python harness that verifies a TeacherZone schedule migration — given an org's raw occurrence export and its converted RRULE template (+ edge-case sheet), prove whether the conversion faithfully preserved the schedule.

**Architecture:** Re-implement the *inverse* transform: expand template recurrence rules into concrete occurrences, apply the edge-case exception layer, normalize the raw export into the same occurrence shape, then reconcile bidirectionally under a catalog of domain invariants. Matching uses three layers (timeslot multiset → structural series → name resolution) so the harness runs on all ~200 orgs using only the two files, with optional lookup tables for extra precision.

**Tech Stack:** Python 3.11+, `openpyxl` (xlsx I/O), `python-dateutil` (`rrule` expansion), `pytest` (tests). No network, no DB.

## Global Constraints

- Python 3.11+; dependencies limited to `openpyxl`, `python-dateutil`, `pytest`.
- The verifier MUST be independent of the portal converter — it never imports or calls it.
- NO org-specific data (names, IDs) in code. All org knowledge lives in `verifier/config.py`.
- The harness MUST run using only `(raw.xlsx, template.xlsx)`; lookup tables are optional inputs.
- All datetimes are treated as wall-clock (naive) local time unless a `TimeOffSet` is present; never silently shift wall-clock time across DST.
- Frozen dataclasses for value types; deterministic ordering in all outputs (sort before emit).
- TDD: write the failing test first, see it fail, implement minimally, see it pass, commit.

---

## File Structure

```
schedules/
  requirements.txt
  verifier/
    __init__.py
    config.py          # OrgSchema: column maps, status-code meanings, weekday map
    models.py          # Occurrence, Series, Finding, OrgReport (frozen dataclasses)
    loaders.py         # xlsx -> normalized raw/template/edge records
    rrule_expander.py  # template row -> list[Occurrence] (inverse engine)
    edge_applier.py    # apply cancel/substitute-split/only-this/bank/restore
    matcher.py         # Layer A/B/C matching -> aligned occurrence pairs
    reconciler.py      # bidirectional diff + invariant suite -> list[Finding]
    reporter.py        # OrgReport -> JSON + human summary; fleet roll-up
    cli.py             # argparse entrypoint: verify one org or a fleet dir
  tests/
    conftest.py        # synthetic fixture builders
    test_config.py
    test_loaders.py
    test_rrule_expander.py
    test_edge_applier.py
    test_matcher.py
    test_reconciler.py
    test_reporter.py
    test_e2e.py
    fixtures/          # tiny hand-built xlsx + the Paper Moon pair (gitignored)
```

---

### Task 1: Project scaffold, config schema, and value models

**Files:**
- Create: `requirements.txt`
- Create: `verifier/__init__.py`
- Create: `verifier/config.py`
- Create: `verifier/models.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `verifier.config.OrgSchema` — frozen dataclass with fields:
    `raw_cols: dict[str,str]`, `tpl_cols: dict[str,str]`, `edge_cols: dict[str,str]`,
    `weekday_map: dict[str,int]` (Mon=0..Sun=6),
    `cancelled_attendance_ids: frozenset[int]`,
    `date_formats: tuple[str,...]`.
  - `verifier.config.PAPER_MOON` — an `OrgSchema` instance with the verified column names.
  - `verifier.models.Occurrence` (frozen dataclass): `date: datetime.date`, `start: datetime.time`,
    `end: datetime.time`, `teacher: str|None`, `teacher_id: int|None`, `member: str|None`,
    `member_id: int|None`, `group_id: int|None`, `location: str|None`, `room: str|None`,
    `source: str` (`'raw'|'template'|'edge'`), `source_id: int|None`,
    `kind: str` (`'normal'|'cancelled'|'substitute'|'adjusted'|'banked'|'restored'`).
    Method `slot_key() -> tuple` returns `(date, start, end)`.
  - `verifier.models.Series` (frozen dataclass): `key: tuple`, `dates: frozenset[datetime.date]`,
    `start: datetime.time`, `end: datetime.time`, `weekday: int`,
    `teacher_id: int|None`, `member_id: int|None`, `group_id: int|None`,
    `open_ended: bool`, `repeat_until: datetime.date|None`.
  - `verifier.models.Finding` (frozen dataclass): `severity: str` (`'error'|'warn'|'info'`),
    `code: str`, `message: str`, `layer: str`, `detail: dict`.
  - `verifier.models.OrgReport` (frozen dataclass): `org: str`, `verdict: str`
    (`'PASS'|'FAIL'|'NEEDS_REVIEW'`), `summary: dict`, `findings: tuple[Finding,...]`,
    `coverage: dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from verifier.config import PAPER_MOON, OrgSchema
from verifier.models import Occurrence
import datetime as dt

def test_paper_moon_schema_has_required_columns():
    s = PAPER_MOON
    assert isinstance(s, OrgSchema)
    assert s.raw_cols["start_time"] == "StartTime"
    assert s.raw_cols["teacher_id"] == "TeacherID"
    assert s.tpl_cols["repeat_until"] == "Repeat Until"
    assert s.edge_cols["student_plan_id"] == "StudentPlanID"
    assert s.weekday_map["Mon"] == 0 and s.weekday_map["Sun"] == 6
    assert 3 in s.cancelled_attendance_ids

def test_occurrence_slot_key():
    o = Occurrence(date=dt.date(2026, 6, 18), start=dt.time(19, 0), end=dt.time(20, 0),
                   teacher="Jeno Somlai", teacher_id=None, member="", member_id=None,
                   group_id=None, location="Main", room=None, source="template",
                   source_id=None, kind="normal")
    assert o.slot_key() == (dt.date(2026, 6, 18), dt.time(19, 0), dt.time(20, 0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pip install -r requirements.txt && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier'`

- [ ] **Step 3: Write requirements and minimal implementation**

```text
# requirements.txt
openpyxl>=3.1
python-dateutil>=2.9
pytest>=8.0
```

```python
# verifier/__init__.py
```

```python
# verifier/models.py
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
```

```python
# verifier/config.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class OrgSchema:
    raw_cols: dict
    tpl_cols: dict
    edge_cols: dict
    weekday_map: dict
    cancelled_attendance_ids: frozenset
    date_formats: tuple

_WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

PAPER_MOON = OrgSchema(
    raw_cols={
        "student_plan_id": "StudentPlanID", "start_time": "StartTime", "end_time": "EndTime",
        "teacher_id": "TeacherID", "substitute_teacher_id": "SubstituteTeacherID",
        "student_id": "StudentID", "room_id": "RoomID", "group_id": "GroupID",
        "status_id": "StatusID", "attendance_status_id": "AttendanceStatusID",
        "bank_status_id": "BankStatusID", "no_end_date_id": "NoEndDateID", "end_by": "EndBy",
        "is_only_this": "IsOnlyThis", "user_type": "UserType",
    },
    tpl_cols={
        "start_date": "Start Date", "start_time": "Start Time", "end_time": "End Time",
        "location": "Location", "instructor": "Instructor(s)", "member": "Member(s)",
        "classes": "Classes", "repeat": "Repeat", "repeat_days": "Repeat Days",
        "repeat_until": "Repeat Until", "room": "Room",
    },
    edge_cols={
        "edge_type": "EdgeCaseTypes", "student_plan_id": "StudentPlanID",
        "teacher_id": "TeacherID", "teacher_name": "TeacherName",
        "student_id": "StudentID", "student_name": "StudentName",
        "group_id": "GroupID", "group_name": "GroupName",
        "start_time": "StartTime", "end_time": "EndTime",
        "is_cancelled": "IsCancelled", "is_banked": "IsBanked", "is_restored": "IsRestored",
        "is_only_this": "IsOnlyThis", "is_adjusted_only_this": "IsAdjustedOnlyThis",
        "is_substitute_following": "IsSubstituteFollowing",
        "is_superseded_following": "IsSupersededFollowing",
        "bank_lesson_id": "BankLessonID",
    },
    weekday_map=dict(_WEEKDAYS),
    cancelled_attendance_ids=frozenset({3}),
    date_formats=("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt verifier/ tests/test_config.py
git commit -m "feat: scaffold verifier with org schema and value models"
```

---

### Task 2: Loaders — xlsx into normalized records

**Files:**
- Create: `verifier/loaders.py`
- Create: `tests/conftest.py`
- Test: `tests/test_loaders.py`

**Interfaces:**
- Consumes: `OrgSchema` (Task 1), `Occurrence` (Task 1).
- Produces:
  - `verifier.loaders.parse_dt(value, schema) -> datetime.datetime|None` — parse a raw cell
    that may be a `datetime`, a string in one of `schema.date_formats`, or `"NULL"`/`None`/`""`.
  - `verifier.loaders.parse_clock(value) -> datetime.time` — parse `"7:00 PM"` style template times.
  - `verifier.loaders.load_raw(path, schema) -> list[dict]` — header-keyed dict rows (str keys
    from row 1), values cleaned of the literal string `"NULL"` (→ `None`).
  - `verifier.loaders.load_template(path, schema, sheet="Schedule Import Template") -> list[dict]`.
  - `verifier.loaders.load_edge(path, schema, sheet="Edge-case schedules") -> list[dict]`.
  - `verifier.loaders.raw_to_occurrence(row, schema) -> Occurrence` — one raw row → `Occurrence`
    with `source="raw"`, `source_id=StudentPlanID`, `kind` derived: `"cancelled"` if
    `attendance_status_id in schema.cancelled_attendance_ids`, else `"substitute"` if
    `substitute_teacher_id` truthy, else `"normal"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/conftest.py
import datetime as dt
import openpyxl
import pytest

@pytest.fixture
def make_xlsx(tmp_path):
    def _make(sheets: dict):  # {sheet_name: (headers, rows)}
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for name, (headers, rows) in sheets.items():
            ws = wb.create_sheet(title=name)
            ws.append(headers)
            for r in rows:
                ws.append(list(r))
        p = tmp_path / "book.xlsx"
        wb.save(p)
        return str(p)
    return _make
```

```python
# tests/test_loaders.py
import datetime as dt
from verifier.config import PAPER_MOON as S
from verifier import loaders

def test_parse_dt_handles_null_and_formats():
    assert loaders.parse_dt("NULL", S) is None
    assert loaders.parse_dt("2026-06-19 03:00:00.000", S) == dt.datetime(2026, 6, 19, 3, 0)
    assert loaders.parse_dt(dt.datetime(2026, 6, 19, 3, 0), S) == dt.datetime(2026, 6, 19, 3, 0)

def test_parse_clock():
    assert loaders.parse_clock("7:00 PM") == dt.time(19, 0)
    assert loaders.parse_clock("8:20 AM") == dt.time(8, 20)

def test_load_raw_strips_null(make_xlsx):
    path = make_xlsx({"Trang tính1": (
        ["StudentPlanID", "StartTime", "EndTime", "TeacherID", "SubstituteTeacherID",
         "StudentID", "AttendanceStatusID", "BankStatusID", "GroupID", "NoEndDateID",
         "EndBy", "IsOnlyThis", "StatusID", "RoomID", "UserType"],
        [[1, "2026-06-18 19:00:00.000", "2026-06-18 20:00:00.000", 10, "NULL",
          99, 0, 0, 0, 555, "NULL", 0, 1, 6384, 2]],
    )})
    rows = loaders.load_raw(path, S)
    assert rows[0]["SubstituteTeacherID"] is None
    occ = loaders.raw_to_occurrence(rows[0], S)
    assert occ.date == dt.date(2026, 6, 18)
    assert occ.start == dt.time(19, 0) and occ.end == dt.time(20, 0)
    assert occ.teacher_id == 10 and occ.member_id == 99
    assert occ.kind == "normal" and occ.source == "raw" and occ.source_id == 1

def test_raw_to_occurrence_marks_cancelled(make_xlsx):
    path = make_xlsx({"Trang tính1": (
        ["StudentPlanID", "StartTime", "EndTime", "TeacherID", "SubstituteTeacherID",
         "StudentID", "AttendanceStatusID", "BankStatusID", "GroupID", "NoEndDateID",
         "EndBy", "IsOnlyThis", "StatusID", "RoomID", "UserType"],
        [[2, "2026-06-18 19:00:00.000", "2026-06-18 20:00:00.000", 10, "NULL",
          99, 3, 0, 0, 555, "NULL", 0, 1, 6384, 2]],
    )})
    occ = loaders.raw_to_occurrence(loaders.load_raw(path, S)[0], S)
    assert occ.kind == "cancelled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loaders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier.loaders'`

- [ ] **Step 3: Write minimal implementation**

```python
# verifier/loaders.py
from __future__ import annotations
import datetime as dt
import openpyxl
from .models import Occurrence

def parse_dt(value, schema):
    if value in (None, "", "NULL"):
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    s = str(value).strip()
    for fmt in schema.date_formats:
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unparseable datetime: {value!r}")

def parse_clock(value):
    if isinstance(value, dt.time):
        return value
    return dt.datetime.strptime(str(value).strip().upper(), "%I:%M %p").time()

def _clean(v):
    return None if (isinstance(v, str) and v.strip() == "NULL") else v

def _load_sheet(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    headers = [str(h) for h in next(it)]
    rows = [{h: _clean(v) for h, v in zip(headers, r)} for r in it]
    wb.close()
    return rows

def load_raw(path, schema):
    return _load_sheet(path, None)

def load_template(path, schema, sheet="Schedule Import Template"):
    return _load_sheet(path, sheet)

def load_edge(path, schema, sheet="Edge-case schedules"):
    return _load_sheet(path, sheet)

def raw_to_occurrence(row, schema):
    c = schema.raw_cols
    st = parse_dt(row.get(c["start_time"]), schema)
    et = parse_dt(row.get(c["end_time"]), schema)
    att = row.get(c["attendance_status_id"]) or 0
    sub = row.get(c["substitute_teacher_id"])
    if int(att) in schema.cancelled_attendance_ids:
        kind = "cancelled"
    elif sub:
        kind = "substitute"
    else:
        kind = "normal"
    return Occurrence(
        date=st.date(), start=st.time(), end=et.time(),
        teacher=None, teacher_id=row.get(c["teacher_id"]),
        member=None, member_id=row.get(c["student_id"]),
        group_id=row.get(c["group_id"]) or None,
        location=None, room=row.get(c["room_id"]),
        source="raw", source_id=row.get(c["student_plan_id"]), kind=kind,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_loaders.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add verifier/loaders.py tests/conftest.py tests/test_loaders.py
git commit -m "feat: load and normalize raw/template/edge xlsx rows"
```

---

### Task 3: RRULE expander — template row to occurrences

**Files:**
- Create: `verifier/rrule_expander.py`
- Test: `tests/test_rrule_expander.py`

**Interfaces:**
- Consumes: `OrgSchema`, `Occurrence`, `loaders.parse_clock`, `loaders.parse_dt`.
- Produces:
  - `verifier.rrule_expander.expand_row(row, schema, window_start, window_end) -> list[Occurrence]`
    — expand one template row into occurrences with `source="template"`, `kind="normal"`.
    Rules: `Repeat="Weekly"` → weekly on each day in `Repeat Days` (comma list, mapped via
    `schema.weekday_map`); `"Bi-weekly"` → every 2 weeks; `"Monthly"` → monthly on the start
    weekday's position; blank/`None`/`""` → single occurrence on `Start Date`. End bound is
    `min(Repeat Until, window_end)`; if `Repeat Until` is empty, bound is `window_end`
    (open-ended). Start bound is `max(Start Date, window_start)`. Wall-clock `start`/`end`
    times are constant across the whole series (DST-safe by construction — date iteration only).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rrule_expander.py
import datetime as dt
from verifier.config import PAPER_MOON as S
from verifier.rrule_expander import expand_row

W0, W1 = dt.date(2026, 1, 1), dt.date(2026, 12, 31)

def _row(**kw):
    base = {"Start Date": dt.datetime(2026, 6, 18), "Start Time": "7:00 PM",
            "End Time": "8:00 PM", "Instructor(s)": "Jeno Somlai", "Member(s)": "",
            "Classes": "Jazz", "Repeat": "Weekly", "Repeat Days": "Thu",
            "Repeat Until": dt.datetime(2026, 7, 3), "Location": "Main", "Room": None}
    base.update(kw)
    return base

def test_weekly_bounded_expands_each_thursday():
    occ = expand_row(_row(), S, W0, W1)
    days = sorted(o.date for o in occ)
    assert days == [dt.date(2026, 6, 18), dt.date(2026, 6, 25), dt.date(2026, 7, 2)]
    assert all(o.start == dt.time(19, 0) and o.end == dt.time(20, 0) for o in occ)
    assert all(o.source == "template" and o.kind == "normal" for o in occ)

def test_open_ended_uses_window_end():
    occ = expand_row(_row(**{"Repeat Until": None}), S, dt.date(2026, 6, 18), dt.date(2026, 7, 9))
    assert sorted(o.date for o in occ) == [dt.date(2026, 6, 18), dt.date(2026, 6, 25),
                                           dt.date(2026, 7, 2), dt.date(2026, 7, 9)]

def test_biweekly_skips_alternate_weeks():
    occ = expand_row(_row(**{"Repeat": "Bi-weekly", "Repeat Until": dt.datetime(2026, 7, 16)}),
                     S, W0, W1)
    assert sorted(o.date for o in occ) == [dt.date(2026, 6, 18), dt.date(2026, 7, 2),
                                           dt.date(2026, 7, 16)]

def test_blank_repeat_is_single_occurrence():
    occ = expand_row(_row(**{"Repeat": "", "Repeat Days": "", "Repeat Until": None}), S, W0, W1)
    assert [o.date for o in occ] == [dt.date(2026, 6, 18)]

def test_multi_day_weekly():
    occ = expand_row(_row(**{"Repeat Days": "Mon, Wed", "Repeat Until": dt.datetime(2026, 6, 24)}),
                     S, W0, W1)
    assert sorted(o.date for o in occ) == [dt.date(2026, 6, 22), dt.date(2026, 6, 24)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rrule_expander.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier.rrule_expander'`

- [ ] **Step 3: Write minimal implementation**

```python
# verifier/rrule_expander.py
from __future__ import annotations
import datetime as dt
from dateutil.rrule import rrule, WEEKLY, MONTHLY
from .models import Occurrence
from .loaders import parse_clock, parse_dt

def _days(row, schema):
    raw = row.get(schema.tpl_cols["repeat_days"])
    if not raw:
        return None
    return [schema.weekday_map[d.strip()] for d in str(raw).split(",") if d.strip()]

def expand_row(row, schema, window_start, window_end):
    c = schema.tpl_cols
    sd = parse_dt(row.get(c["start_date"]), schema).date()
    start = parse_clock(row.get(c["start_time"]))
    end = parse_clock(row.get(c["end_time"]))
    repeat = (row.get(c["repeat"]) or "").strip()
    ru_dt = parse_dt(row.get(c["repeat_until"]), schema)
    ru = ru_dt.date() if ru_dt else None

    lo = max(sd, window_start)
    hi = min(ru, window_end) if ru else window_end

    def occ(d):
        return Occurrence(date=d, start=start, end=end,
                          teacher=row.get(c["instructor"]) or None, teacher_id=None,
                          member=row.get(c["member"]) or None, member_id=None,
                          group_id=None, location=row.get(c["location"]),
                          room=row.get(c["room"]), source="template", source_id=None,
                          kind="normal")

    if repeat in ("", "None"):
        return [occ(sd)] if window_start <= sd <= window_end else []

    if repeat == "Monthly":
        rule = rrule(MONTHLY, dtstart=dt.datetime.combine(sd, dt.time()),
                     until=dt.datetime.combine(hi, dt.time()))
        return [occ(d.date()) for d in rule if d.date() >= lo]

    interval = 2 if repeat == "Bi-weekly" else 1
    days = _days(row, schema) or [sd.weekday()]
    rule = rrule(WEEKLY, interval=interval, byweekday=days,
                 dtstart=dt.datetime.combine(sd, dt.time()),
                 until=dt.datetime.combine(hi, dt.time()))
    return [occ(d.date()) for d in rule if d.date() >= lo]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rrule_expander.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add verifier/rrule_expander.py tests/test_rrule_expander.py
git commit -m "feat: expand template recurrence rules into occurrences"
```

---

### Task 4: Edge applier — apply the exception layer

**Files:**
- Create: `verifier/edge_applier.py`
- Test: `tests/test_edge_applier.py`

**Interfaces:**
- Consumes: `OrgSchema`, `Occurrence`, `loaders.parse_dt`.
- Produces:
  - `verifier.edge_applier.EdgeFact` (frozen dataclass): `student_plan_id: int`,
    `edge_type: str`, `date: datetime.date`, `start: datetime.time`, `end: datetime.time`,
    `teacher_id: int|None`, `teacher_name: str|None`, `student_id: int|None`,
    `student_name: str|None`, `group_id: int|None`, `group_name: str|None`,
    `is_cancelled: bool`, `is_following: bool`, `is_only_this: bool`, `is_banked: bool`,
    `is_restored: bool`.
  - `verifier.edge_applier.edge_to_fact(row, schema) -> EdgeFact` — `Yes/No` → bool.
  - `verifier.edge_applier.apply_edges(expanded, edges, schema) -> tuple[list[Occurrence], dict]`
    — returns `(adjusted_occurrences, stats)`. Behaviour:
    cancelled edge → matching expanded occurrence on `slot_key()` is re-tagged `kind="cancelled"`;
    one-off substitute (not following) → matching occurrence re-tagged `kind="substitute"` and
    `teacher` set to the edge's `teacher_name`; following-substitute → that occurrence **and all
    later same-slot occurrences in the same series** re-tagged `kind="substitute"` with the
    substitute teacher; only-this adjustment → matching occurrence re-tagged `kind="adjusted"`.
    `stats` counts each action and any edge with no matching expanded occurrence
    (`unmatched_edges`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_edge_applier.py
import datetime as dt
from verifier.config import PAPER_MOON as S
from verifier.models import Occurrence
from verifier.edge_applier import edge_to_fact, apply_edges

def _occ(d, teacher="Jeno", tid=10, sid=99, start=(19, 0), end=(20, 0), kind="normal"):
    return Occurrence(date=d, start=dt.time(*start), end=dt.time(*end), teacher=teacher,
                      teacher_id=tid, member="M", member_id=sid, group_id=None, location="Main",
                      room=None, source="template", source_id=None, kind=kind)

def _edge_row(**kw):
    base = {"EdgeCaseTypes": "Substitute", "StudentPlanID": 1, "TeacherID": 77,
            "TeacherName": "Sub Teacher", "StudentID": 99, "StudentName": "M", "GroupID": 0,
            "GroupName": "", "StartTime": dt.datetime(2026, 6, 25, 19, 0),
            "EndTime": dt.datetime(2026, 6, 25, 20, 0), "IsCancelled": "No", "IsBanked": "No",
            "IsRestored": "No", "IsOnlyThis": "No", "IsAdjustedOnlyThis": "No",
            "IsSubstituteFollowing": "No", "IsSupersededFollowing": "No", "BankLessonID": None}
    base.update(kw)
    return base

def test_edge_to_fact_bools():
    f = edge_to_fact(_edge_row(IsCancelled="Yes", IsSubstituteFollowing="Yes"), S)
    assert f.is_cancelled and f.is_following and f.student_plan_id == 1
    assert f.teacher_name == "Sub Teacher" and f.date == dt.date(2026, 6, 25)

def test_cancelled_edge_retags_occurrence():
    occ = [_occ(dt.date(2026, 6, 18)), _occ(dt.date(2026, 6, 25))]
    edges = [edge_to_fact(_edge_row(EdgeCaseTypes="Cancelled", IsCancelled="Yes"), S)]
    out, stats = apply_edges(occ, edges, S)
    tagged = [o for o in out if o.date == dt.date(2026, 6, 25)][0]
    assert tagged.kind == "cancelled" and stats["cancelled"] == 1

def test_oneoff_substitute_swaps_only_one():
    occ = [_occ(dt.date(2026, 6, 18)), _occ(dt.date(2026, 6, 25)), _occ(dt.date(2026, 7, 2))]
    edges = [edge_to_fact(_edge_row(), S)]  # substitute on 6/25, not following
    out, _ = apply_edges(occ, edges, S)
    subs = [o for o in out if o.kind == "substitute"]
    assert [o.date for o in subs] == [dt.date(2026, 6, 25)]
    assert subs[0].teacher == "Sub Teacher"

def test_following_substitute_swaps_from_date_forward():
    occ = [_occ(dt.date(2026, 6, 18)), _occ(dt.date(2026, 6, 25)), _occ(dt.date(2026, 7, 2))]
    edges = [edge_to_fact(_edge_row(IsSubstituteFollowing="Yes"), S)]
    out, _ = apply_edges(occ, edges, S)
    subs = sorted(o.date for o in out if o.kind == "substitute")
    assert subs == [dt.date(2026, 6, 25), dt.date(2026, 7, 2)]

def test_unmatched_edge_is_counted():
    occ = [_occ(dt.date(2026, 6, 18))]
    edges = [edge_to_fact(_edge_row(StartTime=dt.datetime(2099, 1, 1, 19, 0),
                                    EndTime=dt.datetime(2099, 1, 1, 20, 0)), S)]
    _, stats = apply_edges(occ, edges, S)
    assert stats["unmatched_edges"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge_applier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier.edge_applier'`

- [ ] **Step 3: Write minimal implementation**

```python
# verifier/edge_applier.py
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, replace
from .loaders import parse_dt

@dataclass(frozen=True)
class EdgeFact:
    student_plan_id: int
    edge_type: str
    date: dt.date
    start: dt.time
    end: dt.time
    teacher_id: int | None
    teacher_name: str | None
    student_id: int | None
    student_name: str | None
    group_id: int | None
    group_name: str | None
    is_cancelled: bool
    is_following: bool
    is_only_this: bool
    is_banked: bool
    is_restored: bool

def _yes(v):
    return str(v).strip().lower() == "yes"

def edge_to_fact(row, schema):
    c = schema.edge_cols
    st = parse_dt(row.get(c["start_time"]), schema)
    et = parse_dt(row.get(c["end_time"]), schema)
    return EdgeFact(
        student_plan_id=row.get(c["student_plan_id"]),
        edge_type=row.get(c["edge_type"]) or "",
        date=st.date(), start=st.time(), end=et.time(),
        teacher_id=row.get(c["teacher_id"]), teacher_name=row.get(c["teacher_name"]),
        student_id=row.get(c["student_id"]), student_name=row.get(c["student_name"]),
        group_id=row.get(c["group_id"]) or None, group_name=row.get(c["group_name"]),
        is_cancelled=_yes(row.get(c["is_cancelled"])),
        is_following=_yes(row.get(c["is_substitute_following"])) or _yes(row.get(c["is_superseded_following"])),
        is_only_this=_yes(row.get(c["is_only_this"])) or _yes(row.get(c["is_adjusted_only_this"])),
        is_banked=_yes(row.get(c["is_banked"])),
        is_restored=_yes(row.get(c["is_restored"])),
    )

def apply_edges(expanded, edges, schema):
    occ = list(expanded)
    stats = {"cancelled": 0, "substitute": 0, "following_substitute": 0,
             "adjusted": 0, "unmatched_edges": 0}

    def same_series(o, e):
        return o.start == e.start and o.end == e.end

    for e in edges:
        idxs = [i for i, o in enumerate(occ) if o.slot_key() == (e.date, e.start, e.end)]
        if not idxs:
            stats["unmatched_edges"] += 1
            continue
        if e.is_cancelled:
            for i in idxs:
                occ[i] = replace(occ[i], kind="cancelled")
            stats["cancelled"] += 1
        elif e.is_only_this:
            for i in idxs:
                occ[i] = replace(occ[i], kind="adjusted")
            stats["adjusted"] += 1
        elif e.is_following:
            for i, o in enumerate(occ):
                if same_series(o, e) and o.date >= e.date:
                    occ[i] = replace(o, kind="substitute", teacher=e.teacher_name)
            stats["following_substitute"] += 1
        else:  # one-off substitute
            for i in idxs:
                occ[i] = replace(occ[i], kind="substitute", teacher=e.teacher_name)
            stats["substitute"] += 1
    return occ, stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_edge_applier.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add verifier/edge_applier.py tests/test_edge_applier.py
git commit -m "feat: apply edge-case exception layer to expanded occurrences"
```

---

### Task 5: Matcher — Layer A (timeslot multiset) and Layer B (structural series)

**Files:**
- Create: `verifier/matcher.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes: `Occurrence`, `Series`, `OrgSchema`.
- Produces:
  - `verifier.matcher.slot_multiset(occurrences) -> collections.Counter` — keyed by
    `(date, start, end)`, counting occurrences. Used for Layer A.
  - `verifier.matcher.diff_multisets(raw_ms, mig_ms) -> dict` — returns
    `{"missing_in_migration": Counter, "extra_in_migration": Counter}` where missing =
    `raw_ms - mig_ms` and extra = `mig_ms - raw_ms`.
  - `verifier.matcher.build_series(occurrences, side) -> list[Series]` — group occurrences into
    series. For `side="raw"`: key `(teacher_id, member_id, group_id, start, end, weekday)`.
    For `side="migration"`: key `(teacher, member, start, end, weekday)`. `dates` = frozenset of
    occurrence dates; `weekday` = weekday of the earliest date.
  - `verifier.matcher.match_series(raw_series, mig_series) -> list[tuple]` — Layer B bipartite
    match: for each `(weekday, start, end)` timeslot bucket, pair raw and migration series by
    descending date-set Jaccard similarity (greedy, highest first). Returns list of
    `(raw_series|None, mig_series|None, jaccard: float)` covering every series exactly once
    (unpaired series appear with `None` on the missing side and `jaccard=0.0`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_matcher.py
import datetime as dt
from collections import Counter
from verifier.models import Occurrence
from verifier import matcher

def _o(d, tid=10, sid=99, teacher="Jeno", member="M", start=(19, 0), end=(20, 0), source="raw"):
    return Occurrence(date=d, start=dt.time(*start), end=dt.time(*end), teacher=teacher,
                      teacher_id=tid, member=member, member_id=sid, group_id=None, location=None,
                      room=None, source=source, source_id=None, kind="normal")

def test_slot_multiset_and_diff():
    raw = [_o(dt.date(2026, 6, 18)), _o(dt.date(2026, 6, 25))]
    mig = [_o(dt.date(2026, 6, 18), source="template")]
    d = matcher.diff_multisets(matcher.slot_multiset(raw), matcher.slot_multiset(mig))
    assert d["missing_in_migration"][(dt.date(2026, 6, 25), dt.time(19, 0), dt.time(20, 0))] == 1
    assert sum(d["extra_in_migration"].values()) == 0

def test_build_series_groups_by_entity():
    raw = [_o(dt.date(2026, 6, 18)), _o(dt.date(2026, 6, 25)),
           _o(dt.date(2026, 6, 18), tid=20, sid=88)]
    series = matcher.build_series(raw, side="raw")
    assert len(series) == 2
    big = max(series, key=lambda s: len(s.dates))
    assert big.dates == frozenset({dt.date(2026, 6, 18), dt.date(2026, 6, 25)})
    assert big.weekday == 3  # Thursday

def test_match_series_pairs_by_date_overlap():
    raw = matcher.build_series([_o(dt.date(2026, 6, 18)), _o(dt.date(2026, 6, 25))], side="raw")
    mig = matcher.build_series([_o(dt.date(2026, 6, 18), source="template"),
                               _o(dt.date(2026, 6, 25), source="template")], side="migration")
    pairs = matcher.match_series(raw, mig)
    assert len(pairs) == 1
    r, m, j = pairs[0]
    assert r is not None and m is not None and j == 1.0

def test_match_series_reports_unpaired():
    raw = matcher.build_series([_o(dt.date(2026, 6, 18))], side="raw")
    mig = matcher.build_series([_o(dt.date(2026, 7, 9), source="template",
                                   start=(8, 0), end=(9, 0))], side="migration")
    pairs = matcher.match_series(raw, mig)
    assert any(r is not None and m is None for r, m, _ in pairs)
    assert any(r is None and m is not None for r, m, _ in pairs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_matcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier.matcher'`

- [ ] **Step 3: Write minimal implementation**

```python
# verifier/matcher.py
from __future__ import annotations
from collections import Counter, defaultdict
from .models import Series

def slot_multiset(occurrences):
    return Counter(o.slot_key() for o in occurrences)

def diff_multisets(raw_ms, mig_ms):
    return {"missing_in_migration": raw_ms - mig_ms,
            "extra_in_migration": mig_ms - raw_ms}

def build_series(occurrences, side):
    groups = defaultdict(list)
    for o in occurrences:
        if side == "raw":
            key = (o.teacher_id, o.member_id, o.group_id, o.start, o.end)
        else:
            key = (o.teacher, o.member, o.start, o.end)
        groups[key].append(o)
    out = []
    for key, occs in groups.items():
        dates = frozenset(o.date for o in occs)
        first = min(dates)
        sample = occs[0]
        out.append(Series(key=key, dates=dates, start=sample.start, end=sample.end,
                          weekday=first.weekday(),
                          teacher_id=sample.teacher_id, member_id=sample.member_id,
                          group_id=sample.group_id, open_ended=False, repeat_until=None))
    return out

def _jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)

def match_series(raw_series, mig_series):
    buckets = defaultdict(lambda: {"raw": [], "mig": []})
    for s in raw_series:
        buckets[(s.weekday, s.start, s.end)]["raw"].append(s)
    for s in mig_series:
        buckets[(s.weekday, s.start, s.end)]["mig"].append(s)

    pairs = []
    for _, grp in buckets.items():
        candidates = []
        for r in grp["raw"]:
            for m in grp["mig"]:
                candidates.append((_jaccard(r.dates, m.dates), r, m))
        candidates.sort(key=lambda t: t[0], reverse=True)
        used_r, used_m = set(), set()
        for j, r, m in candidates:
            if id(r) in used_r or id(m) in used_m:
                continue
            pairs.append((r, m, j))
            used_r.add(id(r)); used_m.add(id(m))
        for r in grp["raw"]:
            if id(r) not in used_r:
                pairs.append((r, None, 0.0))
        for m in grp["mig"]:
            if id(m) not in used_m:
                pairs.append((None, m, 0.0))
    return pairs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_matcher.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add verifier/matcher.py tests/test_matcher.py
git commit -m "feat: timeslot multiset and structural series matching (layers A/B)"
```

---

### Task 6: Reconciler — bidirectional diff and invariant suite

**Files:**
- Create: `verifier/reconciler.py`
- Test: `tests/test_reconciler.py`

**Interfaces:**
- Consumes: `Occurrence`, `Finding`, `OrgSchema`, `matcher.*`, `edge_applier.EdgeFact`.
- Produces:
  - `verifier.reconciler.in_scope(occurrence) -> bool` — `True` unless `kind` in
    `{"cancelled", "banked"}`.
  - `verifier.reconciler.reconcile(raw_occ, migrated_occ, edge_facts, schema) -> list[Finding]`
    where `migrated_occ` is the edge-adjusted expanded set. Runs:
    - **CONSERVATION**: `slot`-multiset diff of in-scope raw vs in-scope migrated → one `error`
      `Finding` per non-empty `(slot, count)` in `missing_in_migration` (`code="MISSING"`) and
      `extra_in_migration` (`code="EXTRA"`).
    - **CANCELLATION**: every raw `kind="cancelled"` slot must NOT be an in-scope migrated slot;
      else `error` `code="CANCELLED_STILL_LIVE"`.
    - **SUBSTITUTE_PRESERVED**: every raw `kind="substitute"` slot must have a migrated occurrence
      with `kind="substitute"` on the same slot; else `warn` `code="SUBSTITUTE_LOST"`.
    - **EDGE_ORPHAN**: each `EdgeFact` whose `student_plan_id` is not among `raw_occ` source_ids →
      `error` `code="EDGE_ORPHAN"`.
    - **DOUBLE_COUNT**: any migrated slot appearing both as `kind="normal"` and as a substitute/
      adjusted/cancelled variant for the same slot → `error` `code="DOUBLE_COUNT"`.
  - `verifier.reconciler.verdict(findings) -> str` — `"FAIL"` if any `error`; else
    `"NEEDS_REVIEW"` if any `warn`; else `"PASS"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reconciler.py
import datetime as dt
from verifier.config import PAPER_MOON as S
from verifier.models import Occurrence
from verifier import reconciler
from verifier.edge_applier import EdgeFact

def _o(d, source, kind="normal", sid=99, start=(19, 0), end=(20, 0), spid=None):
    return Occurrence(date=d, start=dt.time(*start), end=dt.time(*end), teacher="T",
                      teacher_id=10, member="M", member_id=sid, group_id=None, location=None,
                      room=None, source=source, source_id=spid, kind=kind)

def test_conservation_flags_missing():
    raw = [_o(dt.date(2026, 6, 18), "raw"), _o(dt.date(2026, 6, 25), "raw")]
    mig = [_o(dt.date(2026, 6, 18), "template")]
    f = reconciler.reconcile(raw, mig, [], S)
    codes = {x.code for x in f}
    assert "MISSING" in codes
    assert reconciler.verdict(f) == "FAIL"

def test_clean_round_trip_passes():
    raw = [_o(dt.date(2026, 6, 18), "raw"), _o(dt.date(2026, 6, 25), "raw")]
    mig = [_o(dt.date(2026, 6, 18), "template"), _o(dt.date(2026, 6, 25), "template")]
    f = reconciler.reconcile(raw, mig, [], S)
    assert reconciler.verdict(f) == "PASS"

def test_cancelled_still_live_is_error():
    raw = [_o(dt.date(2026, 6, 18), "raw", kind="cancelled")]
    mig = [_o(dt.date(2026, 6, 18), "template", kind="normal")]
    f = reconciler.reconcile(raw, mig, [], S)
    assert "CANCELLED_STILL_LIVE" in {x.code for x in f}

def test_edge_orphan_detected():
    raw = [_o(dt.date(2026, 6, 18), "raw", spid=1)]
    mig = [_o(dt.date(2026, 6, 18), "template")]
    edge = EdgeFact(student_plan_id=999, edge_type="Cancelled", date=dt.date(2026, 6, 18),
                    start=dt.time(19, 0), end=dt.time(20, 0), teacher_id=None, teacher_name=None,
                    student_id=None, student_name=None, group_id=None, group_name=None,
                    is_cancelled=True, is_following=False, is_only_this=False, is_banked=False,
                    is_restored=False)
    f = reconciler.reconcile(raw, mig, [edge], S)
    assert "EDGE_ORPHAN" in {x.code for x in f}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reconciler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier.reconciler'`

- [ ] **Step 3: Write minimal implementation**

```python
# verifier/reconciler.py
from __future__ import annotations
from collections import Counter
from .models import Finding
from . import matcher

def in_scope(o):
    return o.kind not in ("cancelled", "banked")

def reconcile(raw_occ, migrated_occ, edge_facts, schema):
    findings = []
    raw_live = [o for o in raw_occ if in_scope(o)]
    mig_live = [o for o in migrated_occ if in_scope(o)]

    diff = matcher.diff_multisets(matcher.slot_multiset(raw_live),
                                  matcher.slot_multiset(mig_live))
    for slot, n in sorted(diff["missing_in_migration"].items()):
        findings.append(Finding("error", "MISSING",
                                f"{n} raw occurrence(s) at {slot} not in migration",
                                "conservation", {"slot": str(slot), "count": n}))
    for slot, n in sorted(diff["extra_in_migration"].items()):
        findings.append(Finding("error", "EXTRA",
                                f"{n} migrated occurrence(s) at {slot} not in raw",
                                "conservation", {"slot": str(slot), "count": n}))

    mig_live_slots = Counter(o.slot_key() for o in mig_live)
    for o in raw_occ:
        if o.kind == "cancelled" and mig_live_slots.get(o.slot_key()):
            findings.append(Finding("error", "CANCELLED_STILL_LIVE",
                                    f"cancelled raw lesson at {o.slot_key()} is live in migration",
                                    "cancellation", {"slot": str(o.slot_key())}))

    mig_sub_slots = {o.slot_key() for o in migrated_occ if o.kind == "substitute"}
    for o in raw_occ:
        if o.kind == "substitute" and o.slot_key() not in mig_sub_slots:
            findings.append(Finding("warn", "SUBSTITUTE_LOST",
                                    f"raw substitute at {o.slot_key()} not represented",
                                    "substitute", {"slot": str(o.slot_key())}))

    raw_spids = {o.source_id for o in raw_occ}
    for e in edge_facts:
        if e.student_plan_id not in raw_spids:
            findings.append(Finding("error", "EDGE_ORPHAN",
                                    f"edge StudentPlanID {e.student_plan_id} absent from raw",
                                    "structural", {"student_plan_id": e.student_plan_id}))

    by_slot = {}
    for o in migrated_occ:
        by_slot.setdefault(o.slot_key(), set()).add(o.kind)
    for slot, kinds in sorted(by_slot.items()):
        if "normal" in kinds and kinds & {"substitute", "adjusted", "cancelled"}:
            findings.append(Finding("error", "DOUBLE_COUNT",
                                    f"slot {slot} has both normal and exception occurrences",
                                    "structural", {"slot": str(slot)}))
    return findings

def verdict(findings):
    if any(f.severity == "error" for f in findings):
        return "FAIL"
    if any(f.severity == "warn" for f in findings):
        return "NEEDS_REVIEW"
    return "PASS"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reconciler.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add verifier/reconciler.py tests/test_reconciler.py
git commit -m "feat: bidirectional reconciliation with domain invariant suite"
```

---

### Task 7: Reporter and orchestration — per-org report + fleet roll-up

**Files:**
- Create: `verifier/reporter.py`
- Test: `tests/test_reporter.py`

**Interfaces:**
- Consumes: all prior modules.
- Produces:
  - `verifier.reporter.verify_org(raw_path, tpl_path, schema, org_name) -> OrgReport` — the full
    pipeline: load raw/template/edge → raw occurrences → compute window
    `[min, max]` of raw occurrence dates → expand every template row over the window →
    edge facts → `apply_edges` → `reconcile` → build `OrgReport` with `summary`
    (`raw_in_scope`, `migrated_in_scope`, `findings_by_code`), `coverage`
    (`edge_unmatched`, `series_matched`, `series_unpaired`), and `verdict`.
  - `verifier.reporter.report_to_json(report) -> str` — deterministic `json.dumps`
    (`sort_keys=True, indent=2`), Findings as dicts.
  - `verifier.reporter.fleet_rollup(reports) -> list[dict]` — `[{"org", "verdict",
    "error_count", "warn_count"}]` sorted by org name.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporter.py
import json
from verifier.models import OrgReport, Finding
from verifier import reporter

def test_report_to_json_is_deterministic():
    r = OrgReport(org="X", verdict="PASS", summary={"raw_in_scope": 3},
                  findings=(Finding("info", "OK", "m", "l", {}),), coverage={})
    out = reporter.report_to_json(r)
    assert json.loads(out)["verdict"] == "PASS"
    assert reporter.report_to_json(r) == out  # stable

def test_fleet_rollup_counts_and_sorts():
    reps = [
        OrgReport("Bravo", "FAIL", {}, (Finding("error", "E", "m", "l", {}),), {}),
        OrgReport("Alpha", "PASS", {}, (), {}),
    ]
    roll = reporter.fleet_rollup(reps)
    assert [r["org"] for r in roll] == ["Alpha", "Bravo"]
    assert roll[1]["error_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reporter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier.reporter'`

- [ ] **Step 3: Write minimal implementation**

```python
# verifier/reporter.py
from __future__ import annotations
import json
from collections import Counter
from dataclasses import asdict
from .models import OrgReport
from . import loaders, rrule_expander, edge_applier, reconciler, matcher

def verify_org(raw_path, tpl_path, schema, org_name):
    raw_rows = loaders.load_raw(raw_path, schema)
    tpl_rows = loaders.load_template(tpl_path, schema)
    try:
        edge_rows = loaders.load_edge(tpl_path, schema)
    except KeyError:
        edge_rows = []

    raw_occ = [loaders.raw_to_occurrence(r, schema) for r in raw_rows]
    dates = [o.date for o in raw_occ]
    win_lo, win_hi = min(dates), max(dates)

    expanded = []
    for row in tpl_rows:
        expanded.extend(rrule_expander.expand_row(row, schema, win_lo, win_hi))
    edge_facts = [edge_applier.edge_to_fact(r, schema) for r in edge_rows]
    migrated, edge_stats = edge_applier.apply_edges(expanded, edge_facts, schema)

    findings = reconciler.reconcile(raw_occ, migrated, edge_facts, schema)

    raw_series = matcher.build_series([o for o in raw_occ if reconciler.in_scope(o)], "raw")
    mig_series = matcher.build_series([o for o in migrated if reconciler.in_scope(o)], "migration")
    pairs = matcher.match_series(raw_series, mig_series)

    summary = {
        "raw_in_scope": sum(1 for o in raw_occ if reconciler.in_scope(o)),
        "migrated_in_scope": sum(1 for o in migrated if reconciler.in_scope(o)),
        "findings_by_code": dict(Counter(f.code for f in findings)),
    }
    coverage = {
        "edge_unmatched": edge_stats["unmatched_edges"],
        "series_matched": sum(1 for r, m, _ in pairs if r and m),
        "series_unpaired": sum(1 for r, m, _ in pairs if not (r and m)),
    }
    return OrgReport(org=org_name, verdict=reconciler.verdict(findings),
                     summary=summary, findings=tuple(findings), coverage=coverage)

def report_to_json(report):
    d = asdict(report)
    d["findings"] = [asdict(f) if hasattr(f, "__dataclass_fields__") else f
                     for f in report.findings]
    return json.dumps(d, sort_keys=True, indent=2, default=str)

def fleet_rollup(reports):
    out = []
    for r in reports:
        out.append({
            "org": r.org, "verdict": r.verdict,
            "error_count": sum(1 for f in r.findings if f.severity == "error"),
            "warn_count": sum(1 for f in r.findings if f.severity == "warn"),
        })
    return sorted(out, key=lambda x: x["org"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reporter.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add verifier/reporter.py tests/test_reporter.py
git commit -m "feat: per-org report assembly and fleet roll-up"
```

---

### Task 8: CLI and end-to-end verification on the Paper Moon fixture

**Files:**
- Create: `verifier/cli.py`
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: `reporter.verify_org`, `reporter.report_to_json`, `reporter.fleet_rollup`,
  `config.PAPER_MOON`.
- Produces:
  - `verifier.cli.main(argv) -> int` — `argparse`: `--raw PATH --template PATH [--org NAME]`
    prints the per-org JSON report and returns `0` on PASS, `2` on NEEDS_REVIEW, `1` on FAIL.
    `--fleet DIR` mode: each subdir containing `*_Raw_Data.xlsx` + `*_Converted_Template.xlsx`
    is verified; prints the fleet roll-up JSON and returns `0` only if all orgs PASS.

- [ ] **Step 1: Write the failing test**

Place the real fixtures in `tests/fixtures/` first:
```bash
cp Paper_Moon_Music_Raw_Data.xlsx tests/fixtures/
cp Paper_Moon_Music_Converted_Template.xlsx tests/fixtures/
```

```python
# tests/test_e2e.py
import os
import pytest
from verifier.config import PAPER_MOON as S
from verifier import reporter, cli

FX = os.path.join(os.path.dirname(__file__), "fixtures")
RAW = os.path.join(FX, "Paper_Moon_Music_Raw_Data.xlsx")
TPL = os.path.join(FX, "Paper_Moon_Music_Converted_Template.xlsx")

pytestmark = pytest.mark.skipif(not os.path.exists(RAW), reason="fixture not present")

def test_verify_org_runs_and_reports():
    rep = reporter.verify_org(RAW, TPL, S, "Paper Moon Music")
    assert rep.verdict in ("PASS", "NEEDS_REVIEW", "FAIL")
    assert rep.summary["raw_in_scope"] > 0
    assert rep.summary["migrated_in_scope"] > 0
    # the harness must produce findings structurally, not crash
    assert isinstance(rep.summary["findings_by_code"], dict)

def test_cli_returns_exit_code(capsys):
    rc = cli.main(["--raw", RAW, "--template", TPL, "--org", "Paper Moon Music"])
    assert rc in (0, 1, 2)
    out = capsys.readouterr().out
    assert "verdict" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_e2e.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifier.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# verifier/cli.py
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
from .config import PAPER_MOON
from . import reporter

_EXIT = {"PASS": 0, "FAIL": 1, "NEEDS_REVIEW": 2}

def _verify_one(raw, tpl, org):
    rep = reporter.verify_org(raw, tpl, PAPER_MOON, org)
    print(reporter.report_to_json(rep))
    return rep

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description="Verify a schedule migration (black-box).")
    ap.add_argument("--raw")
    ap.add_argument("--template")
    ap.add_argument("--org", default="org")
    ap.add_argument("--fleet")
    args = ap.parse_args(argv)

    if args.fleet:
        reports = []
        for sub in sorted(glob.glob(os.path.join(args.fleet, "*"))):
            raws = glob.glob(os.path.join(sub, "*_Raw_Data.xlsx"))
            tpls = glob.glob(os.path.join(sub, "*_Converted_Template.xlsx"))
            if raws and tpls:
                reports.append(reporter.verify_org(raws[0], tpls[0], PAPER_MOON,
                                                    os.path.basename(sub)))
        print(json.dumps(reporter.fleet_rollup(reports), indent=2))
        return 0 if all(r.verdict == "PASS" for r in reports) else 1

    if not (args.raw and args.template):
        ap.error("--raw and --template are required unless --fleet is used")
    rep = _verify_one(args.raw, args.template, args.org)
    return _EXIT[rep.verdict]

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests). The Paper Moon e2e test asserts the harness runs end-to-end
and produces a structured report. The *content* of that report (how many MISSING/EXTRA
findings) is the actual migration-quality signal you will read manually.

- [ ] **Step 5: Inspect the real result and commit**

Run: `python -m verifier.cli --raw tests/fixtures/Paper_Moon_Music_Raw_Data.xlsx --template tests/fixtures/Paper_Moon_Music_Converted_Template.xlsx --org "Paper Moon Music" | head -60`
Expected: a JSON report with `verdict` and `summary.findings_by_code`. Read the
MISSING/EXTRA/CANCELLED counts — these tell you where the portal converter diverged.

```bash
git add verifier/cli.py tests/test_e2e.py
git commit -m "feat: CLI entrypoint and end-to-end Paper Moon verification"
```

---

### Task 9: Standalone HTML visualization (diff table) + `--html`

**Files:**
- Modify: `verifier/reporter.py` (refactor `verify_org` to share a pipeline; add
  `build_slot_table`, `verify_org_view`, `report_to_html`)
- Modify: `verifier/cli.py` (add `--html PATH`)
- Test: `tests/test_html_report.py`

**Interfaces:**
- Consumes: all prior modules; `OrgReport`.
- Produces:
  - `verifier.reporter._artifacts(raw_path, tpl_path, schema) -> dict` — runs the pipeline once
    and returns `{"raw_occ", "migrated", "edge_facts", "findings", "edge_stats", "pairs"}`.
    Both `verify_org` and `verify_org_view` delegate to it (DRY).
  - `verifier.reporter.build_slot_table(raw_occ, migrated) -> list[dict]` — one entry per distinct
    in-scope `(date, start, end)` slot across both sides, sorted by `(date, start, end)`:
    `{"date": str, "start": str, "end": str, "raw": int, "mig": int, "status": str}` where
    `status` is `"matched"` (raw==mig>0), `"missing"` (raw>mig), `"extra"` (mig>raw).
    Slots that are cancelled/substitute on the raw side are tagged `"cancelled"`/`"substitute"`.
  - `verifier.reporter.verify_org_view(raw_path, tpl_path, schema, org) -> tuple[OrgReport, list[dict]]`
    — returns the report and its slot table.
  - `verifier.reporter.report_to_html(report, slot_table) -> str` — a complete standalone HTML
    document (inline `<style>`, no external assets): verdict banner (class by verdict), a summary
    block, a color-coded slot diff `<table>` (CSS classes `matched/missing/extra/substitute/
    cancelled`), and a findings `<table>`. All values HTML-escaped via `html.escape`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_html_report.py
import datetime as dt
from verifier.models import Occurrence, OrgReport, Finding
from verifier import reporter

def _o(d, source, kind="normal"):
    return Occurrence(date=d, start=dt.time(19, 0), end=dt.time(20, 0), teacher="T",
                      teacher_id=10, member="M", member_id=99, group_id=None, location=None,
                      room=None, source=source, source_id=None, kind=kind)

def test_build_slot_table_classifies_status():
    raw = [_o(dt.date(2026, 6, 18), "raw"), _o(dt.date(2026, 6, 25), "raw")]
    mig = [_o(dt.date(2026, 6, 18), "template")]
    table = reporter.build_slot_table(raw, mig)
    by_date = {r["date"]: r for r in table}
    assert by_date["2026-06-18"]["status"] == "matched"
    assert by_date["2026-06-25"]["status"] == "missing"

def test_report_to_html_is_standalone_and_escaped():
    rep = OrgReport(org="Paper <Moon>", verdict="FAIL", summary={"raw_in_scope": 2},
                    findings=(Finding("error", "MISSING", "1 missing", "conservation", {}),),
                    coverage={})
    table = [{"date": "2026-06-25", "start": "19:00:00", "end": "20:00:00",
              "raw": 1, "mig": 0, "status": "missing"}]
    html = reporter.report_to_html(rep, table)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "Paper &lt;Moon&gt;" in html          # escaped
    assert "FAIL" in html and "missing" in html
    assert "<style>" in html                       # inline CSS, no external file
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_html_report.py -v`
Expected: FAIL with `AttributeError: module 'verifier.reporter' has no attribute 'build_slot_table'`

- [ ] **Step 3: Refactor reporter and add HTML rendering**

Replace the body of `verify_org` in `verifier/reporter.py` with a shared pipeline and add the
new functions:

```python
# verifier/reporter.py  — replace verify_org and append the new functions

import datetime as _dt
import html as _html
from collections import Counter

def _artifacts(raw_path, tpl_path, schema):
    raw_rows = loaders.load_raw(raw_path, schema)
    tpl_rows = loaders.load_template(tpl_path, schema)
    try:
        edge_rows = loaders.load_edge(tpl_path, schema)
    except KeyError:
        edge_rows = []

    raw_occ = [loaders.raw_to_occurrence(r, schema) for r in raw_rows]
    dates = [o.date for o in raw_occ]
    win_lo, win_hi = min(dates), max(dates)

    expanded = []
    for row in tpl_rows:
        expanded.extend(rrule_expander.expand_row(row, schema, win_lo, win_hi))
    edge_facts = [edge_applier.edge_to_fact(r, schema) for r in edge_rows]
    migrated, edge_stats = edge_applier.apply_edges(expanded, edge_facts, schema)
    findings = reconciler.reconcile(raw_occ, migrated, edge_facts, schema)

    raw_series = matcher.build_series([o for o in raw_occ if reconciler.in_scope(o)], "raw")
    mig_series = matcher.build_series([o for o in migrated if reconciler.in_scope(o)], "migration")
    pairs = matcher.match_series(raw_series, mig_series)
    return {"raw_occ": raw_occ, "migrated": migrated, "edge_facts": edge_facts,
            "findings": findings, "edge_stats": edge_stats, "pairs": pairs}

def _build_report(a, org_name):
    findings = a["findings"]
    summary = {
        "raw_in_scope": sum(1 for o in a["raw_occ"] if reconciler.in_scope(o)),
        "migrated_in_scope": sum(1 for o in a["migrated"] if reconciler.in_scope(o)),
        "findings_by_code": dict(Counter(f.code for f in findings)),
    }
    coverage = {
        "edge_unmatched": a["edge_stats"]["unmatched_edges"],
        "series_matched": sum(1 for r, m, _ in a["pairs"] if r and m),
        "series_unpaired": sum(1 for r, m, _ in a["pairs"] if not (r and m)),
    }
    return OrgReport(org=org_name, verdict=reconciler.verdict(findings),
                     summary=summary, findings=tuple(findings), coverage=coverage)

def verify_org(raw_path, tpl_path, schema, org_name):
    return _build_report(_artifacts(raw_path, tpl_path, schema), org_name)

def verify_org_view(raw_path, tpl_path, schema, org_name):
    a = _artifacts(raw_path, tpl_path, schema)
    return _build_report(a, org_name), build_slot_table(a["raw_occ"], a["migrated"])

def build_slot_table(raw_occ, migrated):
    raw_live = Counter(o.slot_key() for o in raw_occ if reconciler.in_scope(o))
    mig_live = Counter(o.slot_key() for o in migrated if reconciler.in_scope(o))
    raw_kind = {}
    for o in raw_occ:
        raw_kind.setdefault(o.slot_key(), o.kind)
    rows = []
    for slot in sorted(set(raw_live) | set(mig_live) |
                       {o.slot_key() for o in raw_occ if o.kind in ("cancelled", "substitute")}):
        d, s, e = slot
        r, m = raw_live.get(slot, 0), mig_live.get(slot, 0)
        k = raw_kind.get(slot)
        if k == "cancelled":
            status = "cancelled"
        elif k == "substitute":
            status = "substitute"
        elif r > m:
            status = "missing"
        elif m > r:
            status = "extra"
        else:
            status = "matched"
        rows.append({"date": str(d), "start": str(s), "end": str(e),
                     "raw": r, "mig": m, "status": status})
    return rows

_CSS = """
body{font-family:system-ui,Arial,sans-serif;margin:2rem;color:#1a1a1a}
.banner{padding:1rem 1.5rem;border-radius:8px;font-size:1.4rem;font-weight:700;color:#fff}
.PASS{background:#15803d}.FAIL{background:#b91c1c}.NEEDS_REVIEW{background:#b45309}
table{border-collapse:collapse;margin-top:1rem;width:100%}
th,td{border:1px solid #ddd;padding:.35rem .6rem;text-align:left;font-size:.9rem}
th{background:#f3f4f6}
tr.matched td{background:#ecfdf5}tr.missing td{background:#fef2f2}
tr.extra td{background:#fff7ed}tr.substitute td{background:#f5f3ff}
tr.cancelled td{background:#f3f4f6;color:#888;text-decoration:line-through}
.legend span{display:inline-block;margin-right:1rem;padding:.2rem .5rem;border-radius:4px}
"""

def _esc(v):
    return _html.escape(str(v))

def report_to_html(report, slot_table):
    parts = ["<!DOCTYPE html>", "<html><head><meta charset='utf-8'>",
             f"<title>Migration report: {_esc(report.org)}</title>",
             f"<style>{_CSS}</style></head><body>",
             f"<h1>Schedule migration verification</h1>",
             f"<p><b>Org:</b> {_esc(report.org)}</p>",
             f"<div class='banner {_esc(report.verdict)}'>{_esc(report.verdict)}</div>",
             "<h2>Summary</h2><ul>"]
    for k, v in sorted(report.summary.items()):
        parts.append(f"<li><b>{_esc(k)}:</b> {_esc(v)}</li>")
    parts.append("</ul>")
    parts.append("<div class='legend'>"
                 "<span class='matched' style='background:#ecfdf5'>matched</span>"
                 "<span class='missing' style='background:#fef2f2'>missing in migration</span>"
                 "<span class='extra' style='background:#fff7ed'>extra in migration</span>"
                 "<span class='substitute' style='background:#f5f3ff'>substitute</span>"
                 "<span class='cancelled' style='background:#f3f4f6'>cancelled</span></div>")
    parts.append("<h2>Slot diff</h2><table><tr><th>Date</th><th>Start</th><th>End</th>"
                 "<th>Raw</th><th>Migrated</th><th>Status</th></tr>")
    for r in slot_table:
        parts.append(
            f"<tr class='{_esc(r['status'])}'><td>{_esc(r['date'])}</td>"
            f"<td>{_esc(r['start'])}</td><td>{_esc(r['end'])}</td>"
            f"<td>{_esc(r['raw'])}</td><td>{_esc(r['mig'])}</td>"
            f"<td>{_esc(r['status'])}</td></tr>")
    parts.append("</table>")
    parts.append("<h2>Findings</h2><table><tr><th>Severity</th><th>Code</th>"
                 "<th>Layer</th><th>Message</th></tr>")
    for f in report.findings:
        parts.append(f"<tr><td>{_esc(f.severity)}</td><td>{_esc(f.code)}</td>"
                     f"<td>{_esc(f.layer)}</td><td>{_esc(f.message)}</td></tr>")
    parts.append("</table></body></html>")
    return "\n".join(parts)
```

Add `--html` to `verifier/cli.py` `_verify_one` / `main`:

```python
# verifier/cli.py — replace _verify_one and add --html handling in main()

def _verify_one(raw, tpl, org, html_path=None):
    if html_path:
        rep, table = reporter.verify_org_view(raw, tpl, PAPER_MOON, org)
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(reporter.report_to_html(rep, table))
        print(f"wrote {html_path}", file=sys.stderr)
    else:
        rep = reporter.verify_org(raw, tpl, PAPER_MOON, org)
    print(reporter.report_to_json(rep))
    return rep
```

In `main()`, add the argument and pass it through:
```python
    ap.add_argument("--html")
    ...
    rep = _verify_one(args.raw, args.template, args.org, args.html)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_html_report.py tests/test_reporter.py tests/test_e2e.py -v`
Expected: PASS (existing reporter/e2e tests still green after the refactor; new HTML tests pass)

- [ ] **Step 5: Generate the real visualization and commit**

Run: `python -m verifier.cli --raw tests/fixtures/Paper_Moon_Music_Raw_Data.xlsx --template tests/fixtures/Paper_Moon_Music_Converted_Template.xlsx --org "Paper Moon Music" --html paper_moon_report.html`
Expected: writes `paper_moon_report.html`; open it in a browser to see the verdict banner and
color-coded slot diff highlighting missing/extra occurrences.

```bash
git add verifier/reporter.py verifier/cli.py tests/test_html_report.py
git commit -m "feat: standalone HTML diff visualization via --html"
```

---

## Self-Review

**Spec coverage:**
- Expand & reconcile model → Tasks 3, 4, 6, 7. ✓
- Scope/window decisions → `verify_org` window computation (Task 7), `in_scope` (Task 6). ✓
- Layer A timeslot multiset → Task 5. ✓
- Layer B structural series → Task 5. ✓
- Layer C name resolution → partially: the edge-sheet bridge carries names into substitute
  occurrences (Task 4 sets `teacher` from `teacher_name`); full lookup-table ingestion is
  deferred (noted below as a follow-up, not in scope of first working harness).
- Tier-1 invariants: Conservation ✓ (Task 6 MISSING/EXTRA), Cancellation ✓, Substitute
  split-aware ✓ (Task 4 following logic + Task 6 SUBSTITUTE_LOST). Bank-lesson balance →
  `in_scope` excludes `banked`; an explicit per-student bank-count invariant is a follow-up
  (no bank data in the Paper Moon fixture to TDD against).
- Tier-2: recurrence integrity ✓ (Task 3 cadence/multi-day/open-ended); DST stability ✓ by
  construction (date-only iteration, constant wall-clock time — Task 3); restore integrity →
  follow-up (no restore data in fixture).
- Tier-3: entity correctness — teacher/member captured on occurrences; group-membership
  completeness is a follow-up invariant.
- Config-driven + schema guard → `OrgSchema` (Task 1); explicit column-presence guard is a
  follow-up hardening step.
- Reporting (JSON + fleet) → Task 7, Task 8. ✓
- Standalone HTML diff visualization (lightweight, no frontend toolchain) → Task 9
  (`build_slot_table`, `report_to_html`, `--html`). ✓

**Deferred to follow-up plans** (called out so they are not silently dropped): explicit
bank-balance invariant, restore-integrity invariant, group-membership completeness check,
lookup-table ingestion for full Layer C, and a strict schema-presence guard. These need org
data that exercises them (absent in Paper Moon) to TDD honestly, so they belong in a second
iteration once real bank/restore exports are available.

**Placeholder scan:** No TBD/TODO; every code step has complete code. ✓

**Type consistency:** `Occurrence`, `Series`, `Finding`, `OrgReport`, `EdgeFact`, `OrgSchema`
signatures are defined once and used consistently across tasks; `slot_key()`, `verdict()`,
`in_scope()`, `expand_row()`, `apply_edges()`, `reconcile()`, `verify_org()` names match
between producer and consumer tasks. ✓
