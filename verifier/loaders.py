from __future__ import annotations
import datetime as dt
from collections import Counter
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

def detect_tz_offset_minutes(raw_rows, tpl_rows, schema):
    """Detect the constant offset (minutes) by which raw times exceed template local
    times. Returns the 30-min-step offset maximizing alignment of raw start-times-of-day
    to the set of template start-times-of-day. local = utc - offset."""
    rc, tc = schema.raw_cols, schema.tpl_cols
    raw_minutes = Counter()
    for r in raw_rows:
        st = parse_dt(r.get(rc["start_time"]), schema)
        if st:
            raw_minutes[st.hour * 60 + st.minute] += 1
    tpl_set = set()
    for r in tpl_rows:
        v = r.get(tc["start_time"])
        if v is None:
            continue
        t = parse_clock(v)
        tpl_set.add(t.hour * 60 + t.minute)
    if not raw_minutes or not tpl_set:
        return 0
    best_off, best_score = 0, -1
    for off in range(0, 1440, 30):
        score = sum(c for m, c in raw_minutes.items() if ((m - off) % 1440) in tpl_set)
        if score > best_score:
            best_score, best_off = score, off
    return best_off

def raw_to_occurrence(row, schema, offset_minutes=0):
    c = schema.raw_cols
    shift = dt.timedelta(minutes=offset_minutes)
    st = parse_dt(row.get(c["start_time"]), schema) - shift
    et = parse_dt(row.get(c["end_time"]), schema) - shift
    att = row.get(c["attendance_status_id"]) or 0
    sub = row.get(c["substitute_teacher_id"])
    if int(att) in schema.cancelled_attendance_ids:
        kind = "cancelled"
    elif sub:
        kind = "substitute"
    else:
        kind = "normal"
    end_by = parse_dt(row.get(c["end_by"]), schema)
    open_ended = bool(row.get(c["no_end_date_id"])) and end_by is None
    return Occurrence(
        date=st.date(), start=st.time(), end=et.time(),
        teacher=None, teacher_id=row.get(c["teacher_id"]),
        member=None, member_id=row.get(c["student_id"]),
        group_id=row.get(c["group_id"]) or None,
        location=None, room=row.get(c["room_id"]),
        source="raw", source_id=row.get(c["student_plan_id"]), kind=kind,
        open_ended=open_ended,
    )
