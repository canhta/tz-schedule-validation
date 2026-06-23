import datetime as dt
from verifier.config import PAPER_MOON as S
from verifier.models import Occurrence
from verifier.edge_applier import edge_to_fact, apply_edges, EdgeFact

def _occ(d, teacher="Jeno", tid=10, sid=99, start=(19, 0), end=(20, 0), kind="normal"):
    return Occurrence(date=d, start=dt.time(*start), end=dt.time(*end), teacher=teacher,
                      teacher_id=tid, member="M", member_id=sid, group_id=None, location="Main",
                      room=None, source="template", source_id=None, kind=kind)

def _fact(d, **kw):
    base = dict(student_plan_id=1, edge_type="Cancelled", date=d, start=dt.time(19, 0),
                end=dt.time(20, 0), teacher_id=77, teacher_name="Sub Teacher", student_id=99,
                student_name="M", group_id=None, group_name="", is_cancelled=False,
                is_following=False, is_only_this=False, is_banked=False, is_restored=False)
    base.update(kw)
    return EdgeFact(**base)

def _edge_row(**kw):
    # v2 edge sheet shape: cancellations carry IsCancelled + ScheduleStatus/AttendanceStatus
    base = {"EdgeCaseTypes": "Cancelled", "StudentPlanID": 1, "TeacherID": 77,
            "TeacherName": "Sub Teacher", "StudentID": 99, "StudentName": "M", "GroupID": 0,
            "GroupName": "", "StartTime": dt.datetime(2026, 6, 25, 19, 0),
            "EndTime": dt.datetime(2026, 6, 25, 20, 0), "IsCancelled": "Yes", "IsBanked": "No",
            "IsRestore": "No", "ScheduleStatus": "Active", "AttendanceStatus": "Student Cancel"}
    base.update(kw)
    return base

def test_edge_to_fact_reads_v2_cancellation():
    f = edge_to_fact(_edge_row(), S)
    assert f.is_cancelled and f.student_plan_id == 1
    assert f.teacher_name == "Sub Teacher" and f.date == dt.date(2026, 6, 25)

def test_cancelled_edge_retags_occurrence():
    occ = [_occ(dt.date(2026, 6, 18)), _occ(dt.date(2026, 6, 25))]
    edges = [edge_to_fact(_edge_row(), S)]
    out, stats = apply_edges(occ, edges, S)
    tagged = [o for o in out if o.date == dt.date(2026, 6, 25)][0]
    assert tagged.kind == "cancelled" and stats["cancelled"] == 1

def test_oneoff_substitute_swaps_only_one():
    occ = [_occ(dt.date(2026, 6, 18)), _occ(dt.date(2026, 6, 25)), _occ(dt.date(2026, 7, 2))]
    edges = [_fact(dt.date(2026, 6, 25), edge_type="Substitute")]  # one-off
    out, _ = apply_edges(occ, edges, S)
    subs = [o for o in out if o.kind == "substitute"]
    assert [o.date for o in subs] == [dt.date(2026, 6, 25)]
    assert subs[0].teacher == "Sub Teacher"

def test_following_substitute_swaps_from_date_forward():
    occ = [_occ(dt.date(2026, 6, 18)), _occ(dt.date(2026, 6, 25)), _occ(dt.date(2026, 7, 2))]
    edges = [_fact(dt.date(2026, 6, 25), is_following=True)]
    out, _ = apply_edges(occ, edges, S)
    subs = sorted(o.date for o in out if o.kind == "substitute")
    assert subs == [dt.date(2026, 6, 25), dt.date(2026, 7, 2)]

def test_unmatched_edge_is_counted():
    occ = [_occ(dt.date(2026, 6, 18))]
    edges = [_fact(dt.date(2099, 1, 1))]
    _, stats = apply_edges(occ, edges, S)
    assert stats["unmatched_edges"] == 1
