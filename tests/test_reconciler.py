import datetime as dt
from verifier.config import PAPER_MOON as S
from verifier.models import Occurrence
from verifier import reconciler
from verifier.edge_applier import EdgeFact

def _o(d, source, kind="normal", sid=99, start=(19, 0), end=(20, 0), spid=None,
       open_ended=False):
    return Occurrence(date=d, start=dt.time(*start), end=dt.time(*end), teacher="T",
                      teacher_id=10, member="M", member_id=sid, group_id=None, location=None,
                      room=None, source=source, source_id=spid, kind=kind,
                      open_ended=open_ended)

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

def test_open_ended_snapshot_tail_does_not_flag_extra():
    # raw is a bounded snapshot (2 weeks); template rule is open-ended (4 weeks expanded).
    raw = [_o(dt.date(2026, 6, 18), "raw", open_ended=True),
           _o(dt.date(2026, 6, 25), "raw", open_ended=True)]
    mig = [_o(dt.date(2026, 6, 18), "template", open_ended=True),
           _o(dt.date(2026, 6, 25), "template", open_ended=True),
           _o(dt.date(2026, 7, 2), "template", open_ended=True),
           _o(dt.date(2026, 7, 9), "template", open_ended=True)]
    f = reconciler.reconcile(raw, mig, [], S)
    assert reconciler.verdict(f) == "PASS"  # tail beyond raw horizon is ignored

def test_open_ended_missing_date_in_window_flags():
    raw = [_o(dt.date(2026, 6, 18), "raw", open_ended=True),
           _o(dt.date(2026, 6, 25), "raw", open_ended=True)]
    mig = [_o(dt.date(2026, 6, 18), "template", open_ended=True)]  # rule fails to make 6/25
    f = reconciler.reconcile(raw, mig, [], S)
    assert "RULE_MISSING_DATE" in {x.code for x in f}

def test_open_ended_flag_mismatch_flags():
    raw = [_o(dt.date(2026, 6, 18), "raw", open_ended=True),
           _o(dt.date(2026, 6, 25), "raw", open_ended=True)]
    mig = [_o(dt.date(2026, 6, 18), "template", open_ended=False),
           _o(dt.date(2026, 6, 25), "template", open_ended=False)]
    f = reconciler.reconcile(raw, mig, [], S)
    assert "RULE_FLAG_MISMATCH" in {x.code for x in f}

def test_missing_series_resolves_name_from_edge():
    # raw enrollment (ids only) with no migration match; edge sheet supplies the names.
    raw = [_o(dt.date(2026, 6, 18), "raw")]  # teacher_id=10, member_id=99
    edge = EdgeFact(student_plan_id=1, edge_type="Cancelled", date=dt.date(2026, 6, 18),
                    start=dt.time(19, 0), end=dt.time(20, 0), teacher_id=10,
                    teacher_name="Jane Doe", student_id=99, student_name="Kid A",
                    group_id=None, group_name=None, is_cancelled=False, is_following=False,
                    is_only_this=False, is_banked=False, is_restored=False)
    f = reconciler.reconcile(raw, [], [edge], S)
    ms = [x for x in f if x.code == "MISSING_SERIES"][0]
    assert ms.detail["teacher"] == "Jane Doe" and ms.detail["member"] == "Kid A"

def test_missing_series_role_tagged_when_unresolved():
    f = reconciler.reconcile([_o(dt.date(2026, 6, 18), "raw")], [], [], S)
    ms = [x for x in f if x.code == "MISSING_SERIES"][0]
    assert ms.detail["teacher"] == "Teacher #10" and ms.detail["member"] == "Student #99"

def test_cancelled_still_live_carries_who():
    raw = [_o(dt.date(2026, 6, 18), "raw", kind="cancelled")]
    mig = [_o(dt.date(2026, 6, 18), "template", kind="normal")]
    c = [x for x in reconciler.reconcile(raw, mig, [], S) if x.code == "CANCELLED_STILL_LIVE"][0]
    assert c.detail["teacher"] == "Teacher #10" and c.detail["member"] == "Student #99"

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
