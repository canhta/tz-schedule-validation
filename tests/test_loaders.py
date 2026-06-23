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
