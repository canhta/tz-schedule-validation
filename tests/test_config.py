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
