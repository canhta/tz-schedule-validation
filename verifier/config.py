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

# Single source of truth: the v2 export format.
# Raw: per-occurrence rows (StartTime in UTC). Template: RRULE rows in local time, with
# permanent substitutes reassigned as the instructor. Edge sheet: cancelled/banked/restored
# only (one-off substitutes live in a separate "Substitute schedules only this" sheet).
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
        "is_cancelled": "IsCancelled", "is_banked": "IsBanked", "is_restore": "IsRestore",
        "schedule_status": "ScheduleStatus", "attendance_status": "AttendanceStatus",
    },
    weekday_map=dict(_WEEKDAYS),
    cancelled_attendance_ids=frozenset({3}),
    date_formats=("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"),
)
