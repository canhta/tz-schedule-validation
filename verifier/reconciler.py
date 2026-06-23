from __future__ import annotations
from collections import Counter
from .models import Finding
from . import matcher

_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def _ds(dates):
    return ", ".join(d.isoformat() for d in sorted(dates))

def in_scope(o):
    return o.kind not in ("cancelled", "banked")

def _label(r, m):
    """Readable, filterable label for a (raw, migration) series pair. Prefers the
    migration side because template rows carry human names; falls back to raw IDs."""
    s = m if m is not None else r
    teacher = m.key[0] if m is not None else (f"#{r.teacher_id}" if r.teacher_id else "?")
    member = m.key[1] if m is not None else (f"#{r.member_id}" if r.member_id else "?")
    wd = _WD[s.weekday] if 0 <= s.weekday < 7 else "?"
    text = f"{teacher or '(no instructor)'} / {member or '(no member)'} · {wd} {s.start}-{s.end}"
    return {"label": text, "teacher": teacher, "member": member,
            "weekday": wd, "start": str(s.start), "end": str(s.end),
            "teacher_id": (r.teacher_id if r else None),
            "member_id": (r.member_id if r else None)}

def _compare_pair(r, m, findings):
    """Compare one matched (raw, migration) series pair and append findings."""
    if r is None:
        findings.append(Finding("error", "EXTRA_SERIES",
                                f"migration series has no raw counterpart ({_label(r, m)['label']})",
                                "series", {"count": len(m.dates), "dates": _ds(m.dates),
                                           **_label(r, m)}))
        return
    if m is None:
        findings.append(Finding("error", "MISSING_SERIES",
                                f"raw series not represented in migration ({_label(r, m)['label']})",
                                "series", {"count": len(r.dates), "dates": _ds(r.dates),
                                           **_label(r, m)}))
        return

    lab = _label(r, m)
    tag = lab["label"]
    if r.open_ended != m.open_ended:
        findings.append(Finding("error", "RULE_FLAG_MISMATCH",
                                f"open-ended flag differs (raw={r.open_ended}, "
                                f"migration={m.open_ended}) — {tag}",
                                "rule", {"raw_open_ended": r.open_ended,
                                         "mig_open_ended": m.open_ended,
                                         "template_repeat_until": str(m.repeat_until), **lab}))

    if r.open_ended or m.open_ended:
        # Rule-equivalence: raw dates must be reproducible by the rule, and within raw's
        # observed horizon the rule must not over-generate. The open-ended tail is ignored.
        missing = r.dates - m.dates
        if missing:
            findings.append(Finding("error", "RULE_MISSING_DATE",
                                    f"{len(missing)} raw occurrence(s) not produced by the rule — {tag}",
                                    "rule", {"count": len(missing), "dates": _ds(missing), **lab}))
        lo, hi = min(r.dates), max(r.dates)
        extra_in_window = {d for d in m.dates if lo <= d <= hi} - r.dates
        if extra_in_window:
            findings.append(Finding("error", "RULE_EXTRA_IN_WINDOW",
                                    f"{len(extra_in_window)} occurrence(s) the rule generates "
                                    f"within raw's horizon are absent from raw — {tag}",
                                    "rule", {"count": len(extra_in_window),
                                             "dates": _ds(extra_in_window), **lab}))
        rc, mc = matcher.infer_cadence_days(r.dates), matcher.infer_cadence_days(m.dates)
        if rc and mc and rc != mc:
            findings.append(Finding("warn", "CADENCE_MISMATCH",
                                    f"cadence differs (raw={rc}d, migration={mc}d) — {tag}",
                                    "rule", {"raw_cadence_days": rc, "mig_cadence_days": mc, **lab}))
    else:
        # Finite series: exact occurrence bijection.
        missing = r.dates - m.dates
        extra = m.dates - r.dates
        if missing:
            findings.append(Finding("error", "MISSING",
                                    f"{len(missing)} finite-series occurrence(s) missing in migration — {tag}",
                                    "conservation", {"count": len(missing), "dates": _ds(missing), **lab}))
        if extra:
            findings.append(Finding("error", "EXTRA",
                                    f"{len(extra)} finite-series occurrence(s) not in raw — {tag}",
                                    "conservation", {"count": len(extra), "dates": _ds(extra), **lab}))

def reconcile(raw_occ, migrated_occ, edge_facts, schema):
    findings = []
    raw_live = [o for o in raw_occ if in_scope(o)]
    mig_live = [o for o in migrated_occ if in_scope(o)]

    raw_series = matcher.build_series(raw_live, "raw")
    mig_series = matcher.build_series(mig_live, "migration")
    for r, m, _j in matcher.match_series(raw_series, mig_series):
        _compare_pair(r, m, findings)

    # Date-specific exception invariants (operate on the full occurrence sets).
    mig_live_slots = Counter(o.slot_key() for o in mig_live)
    for o in raw_occ:
        if o.kind == "cancelled" and mig_live_slots.get(o.slot_key()):
            findings.append(Finding("error", "CANCELLED_STILL_LIVE",
                                    f"cancelled raw lesson at {o.slot_key()} is live in migration",
                                    "cancellation", {"date": str(o.date), "start": str(o.start),
                                                     "end": str(o.end), "student_plan_id": o.source_id}))

    # A substituted lesson is only a problem if its slot is missing from the migration
    # entirely. When a permanent substitute is reassigned as the teacher (v2 model), the
    # lesson still exists as a normal occurrence — that is correct, not "lost".
    for o in raw_occ:
        if o.kind == "substitute" and not mig_live_slots.get(o.slot_key()):
            findings.append(Finding("warn", "SUBSTITUTE_DROPPED",
                                    f"substituted lesson at {o.slot_key()} is absent from migration",
                                    "substitute", {"date": str(o.date), "start": str(o.start),
                                                   "end": str(o.end), "student_plan_id": o.source_id}))

    raw_spids = {o.source_id for o in raw_occ}
    for e in edge_facts:
        if e.student_plan_id not in raw_spids:
            findings.append(Finding("error", "EDGE_ORPHAN",
                                    f"edge StudentPlanID {e.student_plan_id} absent from raw",
                                    "structural", {"student_plan_id": e.student_plan_id}))

    by_slot = {}
    for o in migrated_occ:
        by_slot.setdefault(o.slot_key(), set()).add(o.kind)
    for slot, kinds in sorted(by_slot.items()):
        if "normal" in kinds and kinds & {"substitute", "adjusted", "cancelled"}:
            findings.append(Finding("error", "DOUBLE_COUNT",
                                    f"slot {slot} has both normal and exception occurrences",
                                    "structural", {"slot": str(slot)}))
    return findings

def verdict(findings):
    if any(f.severity == "error" for f in findings):
        return "FAIL"
    if any(f.severity == "warn" for f in findings):
        return "NEEDS_REVIEW"
    return "PASS"
