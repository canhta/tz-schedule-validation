import openpyxl
from verifier.models import OrgReport, Finding
from verifier import defects

def test_write_defects_xlsx(tmp_path):
    rep = OrgReport(
        org="X", verdict="FAIL",
        summary={"findings_by_code": {"RULE_FLAG_MISMATCH": 1}},
        findings=(Finding("error", "RULE_FLAG_MISMATCH", "msg", "rule",
                          {"teacher": "T", "member": "M", "weekday": "Tue",
                           "start": "15:00:00", "end": "15:30:00",
                           "template_repeat_until": "2026-07-15"}),),
        coverage={})
    out = tmp_path / "defects.xlsx"
    defects.write_defects_xlsx(rep, str(out))
    wb = openpyxl.load_workbook(out)
    assert set(wb.sheetnames) == {"Summary", "Defects"}
    d = wb["Defects"]
    assert d.cell(1, 3).value == "Issue"
    assert d.cell(2, 3).value == "RULE_FLAG_MISMATCH"
    assert "Repeat Until" in d.cell(2, 10).value  # the specific value column
    assert d.cell(2, 12).value  # fix hint present
