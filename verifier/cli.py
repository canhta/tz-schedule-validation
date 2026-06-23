from __future__ import annotations
import argparse
import glob
import json
import os
import sys
from .config import PAPER_MOON
from . import reporter, defects

_EXIT = {"PASS": 0, "FAIL": 1, "NEEDS_REVIEW": 2}

def _verify_one(raw, tpl, org, html_path=None, schema=PAPER_MOON, defects_path=None, **sheets):
    if html_path:
        rep, table = reporter.verify_org_view(raw, tpl, schema, org, **sheets)
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(reporter.report_to_html(rep, table))
        print(f"wrote {html_path}", file=sys.stderr)
    else:
        rep = reporter.verify_org(raw, tpl, schema, org, **sheets)
    if defects_path:
        defects.write_defects_xlsx(rep, defects_path)
        print(f"wrote {defects_path}", file=sys.stderr)
    print(reporter.report_to_json(rep))
    return rep

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description="Verify a schedule migration (black-box).")
    ap.add_argument("--raw")
    ap.add_argument("--template")
    ap.add_argument("--org", default="org")
    ap.add_argument("--html")
    ap.add_argument("--defects", help="write a developer defect report (.xlsx)")
    ap.add_argument("--raw-sheet", help="raw data sheet name (default: first sheet)")
    ap.add_argument("--template-sheet", default="Schedule Import Template",
                    help="import template sheet name")
    ap.add_argument("--edge-sheet", default="Edge-case schedules",
                    help="edge-case sheet name ('' or 'none' to skip)")
    ap.add_argument("--fleet")
    args = ap.parse_args(argv)
    schema = PAPER_MOON

    if args.fleet:
        reports = []
        for sub in sorted(glob.glob(os.path.join(args.fleet, "*"))):
            raws = glob.glob(os.path.join(sub, "*_Raw_Data.xlsx"))
            tpls = glob.glob(os.path.join(sub, "*_Converted_Template.xlsx"))
            if raws and tpls:
                reports.append(reporter.verify_org(raws[0], tpls[0], schema,
                                                    os.path.basename(sub)))
        print(json.dumps(reporter.fleet_rollup(reports), indent=2))
        return 0 if all(r.verdict == "PASS" for r in reports) else 1

    if not (args.raw and args.template):
        ap.error("--raw and --template are required unless --fleet is used")
    edge_sheet = None if (args.edge_sheet or "").lower() in ("", "none") else args.edge_sheet
    rep = _verify_one(args.raw, args.template, args.org, args.html, schema, args.defects,
                      raw_sheet=args.raw_sheet, template_sheet=args.template_sheet,
                      edge_sheet=edge_sheet)
    return _EXIT[rep.verdict]

if __name__ == "__main__":
    raise SystemExit(main())
