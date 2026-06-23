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
