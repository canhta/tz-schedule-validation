import json
from verifier.models import OrgReport, Finding
from verifier import reporter

def test_report_to_json_is_deterministic():
    r = OrgReport(org="X", verdict="PASS", summary={"raw_in_scope": 3},
                  findings=(Finding("info", "OK", "m", "l", {}),), coverage={})
    out = reporter.report_to_json(r)
    assert json.loads(out)["verdict"] == "PASS"
    assert reporter.report_to_json(r) == out  # stable

def test_fleet_rollup_counts_and_sorts():
    reps = [
        OrgReport("Bravo", "FAIL", {}, (Finding("error", "E", "m", "l", {}),), {}),
        OrgReport("Alpha", "PASS", {}, (), {}),
    ]
    roll = reporter.fleet_rollup(reps)
    assert [r["org"] for r in roll] == ["Alpha", "Bravo"]
    assert roll[1]["error_count"] == 1
