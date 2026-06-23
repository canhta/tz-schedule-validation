"""Sheet mapping: user picks which sheet is raw / template / edge (no hardcoding)."""
import datetime as dt
from verifier.config import PAPER_MOON as S
from verifier import loaders, server


def test_load_raw_accepts_explicit_sheet(make_xlsx):
    path = make_xlsx({
        "Sheet A": (["X"], [[1]]),
        "Weird Raw Name": (["StudentPlanID"], [[42]]),
    })
    rows = loaders.load_raw(path, S, "Weird Raw Name")
    assert rows == [{"StudentPlanID": 42}]


def test_load_raw_defaults_to_first_sheet(make_xlsx):
    path = make_xlsx({"First": (["A"], [[1]]), "Second": (["B"], [[2]])})
    assert loaders.load_raw(path, S) == [{"A": 1}]


def test_list_sheets_returns_names_in_order(make_xlsx):
    path = make_xlsx({"One": (["A"], []), "Two": (["B"], []), "Three": (["C"], [])})
    assert server.list_sheets(path) == ["One", "Two", "Three"]


def test_guess_sheet_matches_keyword_case_insensitively():
    names = ["Trang tinh1", "Schedule Import Template", "Edge-case schedules"]
    assert server.guess_sheet(names, ["template"]) == "Schedule Import Template"
    assert server.guess_sheet(names, ["edge"]) == "Edge-case schedules"


def test_guess_sheet_falls_back_to_none_when_no_match():
    assert server.guess_sheet(["A", "B"], ["template"]) is None
