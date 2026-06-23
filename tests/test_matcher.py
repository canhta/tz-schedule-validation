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
