import os
import pytest
from verifier.config import PAPER_MOON as S
from verifier import reporter, cli

FX = os.path.join(os.path.dirname(__file__), "fixtures")
RAW = os.path.join(FX, "Paper_Moon_Music_Raw_Schedules_v2.xlsx")
TPL = os.path.join(FX, "all-schedules_template_v2.xlsx")

pytestmark = pytest.mark.skipif(not os.path.exists(RAW), reason="fixture not present")

def test_verify_org_runs_and_reports():
    rep = reporter.verify_org(RAW, TPL, S, "Paper Moon Music")
    assert rep.verdict in ("PASS", "NEEDS_REVIEW", "FAIL")
    assert rep.summary["raw_in_scope"] > 0
    assert rep.summary["migrated_in_scope"] > 0
    # the harness must produce findings structurally, not crash
    assert isinstance(rep.summary["findings_by_code"], dict)

def test_cli_returns_exit_code(capsys):
    rc = cli.main(["--raw", RAW, "--template", TPL, "--org", "Paper Moon Music"])
    assert rc in (0, 1, 2)
    out = capsys.readouterr().out
    assert "verdict" in out
