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

    def g(key):
        col = c.get(key)
        return row.get(col) if col else None

    st = parse_dt(g("start_time"), schema)
    et = parse_dt(g("end_time"), schema)
    return EdgeFact(
        student_plan_id=g("student_plan_id"),
        edge_type=g("edge_type") or "",
        date=st.date(), start=st.time(), end=et.time(),
        teacher_id=g("teacher_id"), teacher_name=g("teacher_name"),
        student_id=g("student_id"), student_name=g("student_name"),
        group_id=g("group_id") or None, group_name=g("group_name"),
        is_cancelled=_yes(g("is_cancelled")),
        is_following=_yes(g("is_substitute_following")) or _yes(g("is_superseded_following")),
        is_only_this=_yes(g("is_only_this")) or _yes(g("is_adjusted_only_this")),
        is_banked=_yes(g("is_banked")),
        is_restored=_yes(g("is_restored")) or _yes(g("is_restore")),
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
