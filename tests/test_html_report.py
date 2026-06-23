import datetime as dt
from verifier.models import Occurrence, OrgReport, Finding
from verifier import reporter

def _o(d, source, kind="normal"):
    return Occurrence(date=d, start=dt.time(19, 0), end=dt.time(20, 0), teacher="T",
                      teacher_id=10, member="M", member_id=99, group_id=None, location=None,
                      room=None, source=source, source_id=None, kind=kind)

def test_build_slot_table_classifies_status():
    raw = [_o(dt.date(2026, 6, 18), "raw"), _o(dt.date(2026, 6, 25), "raw")]
    mig = [_o(dt.date(2026, 6, 18), "template")]
    table = reporter.build_slot_table(raw, mig)
    by_date = {r["date"]: r for r in table}
    assert by_date["2026-06-18"]["status"] == "matched"
    assert by_date["2026-06-25"]["status"] == "missing"

def test_report_to_html_is_standalone_and_escaped():
    rep = OrgReport(org="Paper <Moon>", verdict="FAIL", summary={"raw_in_scope": 2},
                    findings=(Finding("error", "MISSING", "1 missing", "conservation", {}),),
                    coverage={})
    table = [{"date": "2026-06-25", "start": "19:00:00", "end": "20:00:00",
              "raw": 1, "mig": 0, "status": "missing"}]
    html = reporter.report_to_html(rep, table)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "Paper &lt;Moon&gt;" in html          # escaped
    assert "FAIL" in html and "missing" in html
    assert "<style>" in html                       # inline CSS, no external file

def test_report_to_html_has_embedded_xlsx_export():
    import base64
    rep = OrgReport(org="Paper Moon", verdict="FAIL", summary={"findings_by_code": {"MISSING": 1}},
                    findings=(Finding("error", "MISSING", "1 missing", "conservation", {}),),
                    coverage={})
    html = reporter.report_to_html(rep, [])
    assert "downloadDefects()" in html                       # the button + handler
    assert "Paper_Moon_defects.xlsx" in html                 # slugged filename
    # the embedded payload is a real xlsx (zip magic 'PK')
    b64 = html.split("id='defects-data'>")[1].split("</script>")[0].strip()
    assert base64.b64decode(b64)[:2] == b"PK"
