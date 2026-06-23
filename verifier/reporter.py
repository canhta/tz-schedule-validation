from __future__ import annotations
import html as _html
import json
from collections import Counter
from dataclasses import asdict
from .models import OrgReport
from . import loaders, rrule_expander, edge_applier, reconciler, matcher

def _artifacts(raw_path, tpl_path, schema):
    raw_rows = loaders.load_raw(raw_path, schema)
    tpl_rows = loaders.load_template(tpl_path, schema)
    try:
        edge_rows = loaders.load_edge(tpl_path, schema)
    except KeyError:
        edge_rows = []

    offset = loaders.detect_tz_offset_minutes(raw_rows, tpl_rows, schema)
    raw_occ = [loaders.raw_to_occurrence(r, schema, offset) for r in raw_rows]
    dates = [o.date for o in raw_occ]
    win_lo, win_hi = min(dates), max(dates)

    expanded = []
    for row in tpl_rows:
        expanded.extend(rrule_expander.expand_row(row, schema, win_lo, win_hi))
    edge_facts = [edge_applier.edge_to_fact(r, schema) for r in edge_rows]
    migrated, edge_stats = edge_applier.apply_edges(expanded, edge_facts, schema)
    findings = reconciler.reconcile(raw_occ, migrated, edge_facts, schema)

    raw_series = matcher.build_series([o for o in raw_occ if reconciler.in_scope(o)], "raw")
    mig_series = matcher.build_series([o for o in migrated if reconciler.in_scope(o)], "migration")
    pairs = matcher.match_series(raw_series, mig_series)
    return {"raw_occ": raw_occ, "migrated": migrated, "edge_facts": edge_facts,
            "findings": findings, "edge_stats": edge_stats, "pairs": pairs, "offset": offset}

def _build_report(a, org_name):
    findings = a["findings"]
    summary = {
        "raw_in_scope": sum(1 for o in a["raw_occ"] if reconciler.in_scope(o)),
        "migrated_in_scope": sum(1 for o in a["migrated"] if reconciler.in_scope(o)),
        "findings_by_code": dict(Counter(f.code for f in findings)),
    }
    coverage = {
        "tz_offset_minutes": a["offset"],
        "edge_unmatched": a["edge_stats"]["unmatched_edges"],
        "series_matched": sum(1 for r, m, _ in a["pairs"] if r and m),
        "series_unpaired": sum(1 for r, m, _ in a["pairs"] if not (r and m)),
    }
    return OrgReport(org=org_name, verdict=reconciler.verdict(findings),
                     summary=summary, findings=tuple(findings), coverage=coverage)

def verify_org(raw_path, tpl_path, schema, org_name):
    return _build_report(_artifacts(raw_path, tpl_path, schema), org_name)

def verify_org_view(raw_path, tpl_path, schema, org_name):
    a = _artifacts(raw_path, tpl_path, schema)
    return _build_report(a, org_name), build_slot_table(a["raw_occ"], a["migrated"])

def build_slot_table(raw_occ, migrated):
    raw_live = Counter(o.slot_key() for o in raw_occ if reconciler.in_scope(o))
    mig_live = Counter(o.slot_key() for o in migrated if reconciler.in_scope(o))
    raw_kind = {}
    for o in raw_occ:
        raw_kind.setdefault(o.slot_key(), o.kind)
    rows = []
    special = {o.slot_key() for o in raw_occ if o.kind in ("cancelled", "substitute")}
    for slot in sorted(set(raw_live) | set(mig_live) | special):
        d, s, e = slot
        r, m = raw_live.get(slot, 0), mig_live.get(slot, 0)
        k = raw_kind.get(slot)
        if k == "cancelled":
            status = "cancelled"
        elif k == "substitute":
            status = "substitute"
        elif r > m:
            status = "missing"
        elif m > r:
            status = "extra"
        else:
            status = "matched"
        rows.append({"date": str(d), "start": str(s), "end": str(e),
                     "raw": r, "mig": m, "status": status})
    return rows

def report_to_json(report):
    d = asdict(report)
    d["findings"] = [asdict(f) if hasattr(f, "__dataclass_fields__") else f
                     for f in report.findings]
    return json.dumps(d, sort_keys=True, indent=2, default=str)

def fleet_rollup(reports):
    out = []
    for r in reports:
        out.append({
            "org": r.org, "verdict": r.verdict,
            "error_count": sum(1 for f in r.findings if f.severity == "error"),
            "warn_count": sum(1 for f in r.findings if f.severity == "warn"),
        })
    return sorted(out, key=lambda x: x["org"])

_CSS = """
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,Arial,sans-serif;margin:0;color:#1a1a1a;background:#fafafa}
.wrap{max-width:1100px;margin:0 auto;padding:1.5rem}
h1{font-size:1.3rem;margin:.2rem 0}
.muted{color:#666;font-size:.85rem}
.banner{display:inline-block;padding:.5rem 1.1rem;border-radius:8px;font-size:1.1rem;font-weight:700;color:#fff;margin:.5rem 0}
.PASS{background:#15803d}.FAIL{background:#b91c1c}.NEEDS_REVIEW{background:#b45309}
.cards{display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:.6rem .9rem;min-width:120px}
.card .n{font-size:1.3rem;font-weight:700}.card .l{font-size:.72rem;color:#666;text-transform:uppercase;letter-spacing:.03em}
.controls{position:sticky;top:0;background:#fafafa;padding:.7rem 0;border-bottom:1px solid #e5e7eb;z-index:5}
#q{padding:.45rem .6rem;border:1px solid #ccc;border-radius:6px;width:280px;font-size:.9rem}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.6rem}
.chip,.sevbtn{cursor:pointer;border:1px solid #d1d5db;background:#fff;border-radius:999px;padding:.25rem .7rem;font-size:.8rem;user-select:none}
.chip.err{border-color:#fca5a5}.chip.warn{border-color:#fcd34d}
.chip.active,.sevbtn.active{background:#1f2937;color:#fff;border-color:#1f2937}
table{border-collapse:collapse;margin-top:1rem;width:100%;background:#fff}
th,td{border-bottom:1px solid #eee;padding:.45rem .6rem;text-align:left;font-size:.86rem;vertical-align:top}
th{background:#f3f4f6;position:sticky;top:64px}
.sev-error{color:#b91c1c;font-weight:700}.sev-warn{color:#b45309;font-weight:700}.sev-info{color:#2563eb}
code.cd{background:#f3f4f6;border-radius:4px;padding:.1rem .35rem;font-size:.78rem}
details{margin-top:1.5rem;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:.6rem 1rem}
summary{cursor:pointer;font-weight:600}
tr.missing td{background:#fef2f2}tr.extra td{background:#fff7ed}
tr.substitute td{background:#f5f3ff}tr.cancelled td{background:#f3f4f6;color:#888}
"""

_JS = """
const rows=[...document.querySelectorAll('#findings tbody tr')];
let codeF='',sevF='',q='';
function apply(){
  let vis=0;
  rows.forEach(tr=>{
    const ok=(!codeF||tr.dataset.code===codeF)&&(!sevF||tr.dataset.sev===sevF)&&(!q||tr.dataset.text.includes(q));
    tr.style.display=ok?'':'none'; if(ok)vis++;
  });
  document.querySelectorAll('.chip').forEach(c=>c.classList.toggle('active',c.dataset.code===codeF));
  document.querySelectorAll('.sevbtn').forEach(b=>b.classList.toggle('active',b.dataset.sev===sevF));
  document.getElementById('vis').textContent=vis;
}
function setCode(c){codeF=(codeF===c?'':c);apply();}
function setSev(s){sevF=(sevF===s?'':s);apply();}
window.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('q').addEventListener('input',e=>{q=e.target.value.toLowerCase();apply();});
  apply();
});
"""

def _esc(v):
    return _html.escape(str(v))

def report_to_html(report, slot_table):
    from collections import Counter as _C
    code_counts = _C(f.code for f in report.findings)
    sev_of = {}
    for f in report.findings:
        sev_of.setdefault(f.code, f.severity)
    findings = sorted(report.findings,
                      key=lambda f: (0 if f.severity == "error" else 1 if f.severity == "warn" else 2,
                                     f.code))
    # Raw-anchored anomalies only. Global "extra" slots are the expected open-ended tail
    # under rule-equivalence (the real extra signal is in EXTRA_SERIES / RULE_EXTRA_IN_WINDOW
    # findings), so they are not shown here.
    nonmatched = [r for r in slot_table if r["status"] in ("missing", "cancelled", "substitute")]

    p = ["<!DOCTYPE html>", "<html lang='en'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>Migration report: {_esc(report.org)}</title>",
         f"<style>{_CSS}</style></head><body><div class='wrap'>",
         "<h1>Schedule migration verification</h1>",
         f"<div class='muted'>{_esc(report.org)}</div>",
         f"<div class='banner {_esc(report.verdict)}'>{_esc(report.verdict)}</div>"]

    # summary cards
    s, c = report.summary, report.coverage
    cards = [("findings", len(report.findings)),
             ("raw in scope", s.get("raw_in_scope")),
             ("migrated in scope", s.get("migrated_in_scope")),
             ("series matched", c.get("series_matched")),
             ("series unpaired", c.get("series_unpaired")),
             ("tz offset (min)", c.get("tz_offset_minutes"))]
    p.append("<div class='cards'>")
    for label, n in cards:
        p.append(f"<div class='card'><div class='n'>{_esc(n)}</div>"
                 f"<div class='l'>{_esc(label)}</div></div>")
    p.append("</div>")

    # controls
    p.append("<div class='controls'>")
    p.append("<input id='q' placeholder='Search findings (teacher, student, message)…'>")
    p.append(" <span class='muted'>showing <b id='vis'>0</b> findings</span>")
    p.append("<div class='chips'>")
    p.append("<span class='sevbtn' onclick=\"setSev('error')\">errors</span>")
    p.append("<span class='sevbtn' onclick=\"setSev('warn')\">warnings</span>")
    for code, n in sorted(code_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        cls = "chip err" if sev_of[code] == "error" else "chip warn" if sev_of[code] == "warn" else "chip"
        p.append(f"<span class='{cls}' data-code='{_esc(code)}' "
                 f"onclick=\"setCode('{_esc(code)}')\">{_esc(code)} · {n}</span>")
    p.append("</div></div>")

    # findings table
    p.append("<table id='findings'><thead><tr><th>Severity</th><th>Code</th>"
             "<th>Layer</th><th>Message</th></tr></thead><tbody>")
    for f in findings:
        text = _esc(f.message).lower()
        p.append(f"<tr data-code='{_esc(f.code)}' data-sev='{_esc(f.severity)}' "
                 f"data-text='{text}'>"
                 f"<td class='sev-{_esc(f.severity)}'>{_esc(f.severity)}</td>"
                 f"<td><code class='cd'>{_esc(f.code)}</code></td>"
                 f"<td>{_esc(f.layer)}</td><td>{_esc(f.message)}</td></tr>")
    p.append("</tbody></table>")

    # collapsible slot diff (non-matched only)
    p.append(f"<details><summary>Slot diff — {len(nonmatched)} non-matched "
             f"timeslots (matched hidden)</summary>")
    p.append("<table><thead><tr><th>Date</th><th>Start</th><th>End</th><th>Raw</th>"
             "<th>Migrated</th><th>Status</th></tr></thead><tbody>")
    for r in nonmatched:
        p.append(f"<tr class='{_esc(r['status'])}'><td>{_esc(r['date'])}</td>"
                 f"<td>{_esc(r['start'])}</td><td>{_esc(r['end'])}</td>"
                 f"<td>{_esc(r['raw'])}</td><td>{_esc(r['mig'])}</td>"
                 f"<td>{_esc(r['status'])}</td></tr>")
    p.append("</tbody></table></details>")

    p.append(f"<script>{_JS}</script></div></body></html>")
    return "\n".join(p)
