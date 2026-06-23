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
    open_ended = ru is None and repeat not in ("", "None")

    def occ(d):
        return Occurrence(date=d, start=start, end=end,
                          teacher=row.get(c["instructor"]) or None, teacher_id=None,
                          member=row.get(c["member"]) or None, member_id=None,
                          group_id=None, location=row.get(c["location"]),
                          room=row.get(c["room"]), source="template", source_id=None,
                          kind="normal", open_ended=open_ended)

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
