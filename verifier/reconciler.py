from __future__ import annotations
from collections import Counter
from .models import Finding
from . import matcher

_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def _ds(dates):
    return ", ".join(d.isoformat() for d in sorted(dates))

def in_scope(o):
    return o.kind not in ("cancelled", "banked")

def _name_registry(edge_facts, matches):
    """id -> human name for teachers / students / groups, learned from the edge sheet
    (which carries names + ids) and from matched raw<->migration pairs (template names
    aligned to raw ids). Used to resolve raw-only findings to readable names."""
    teacher, student, group = {}, {}, {}
    for e in edge_facts:
        if e.teacher_id and e.teacher_name:
            teacher.setdefault(e.teacher_id, e.teacher_name)
        if e.student_id and e.student_name:
            student.setdefault(e.student_id, e.student_name)
        if e.group_id and e.group_name:
            group.setdefault(e.group_id, e.group_name)
    for r, m, _j in matches:
        if r is not None and m is not None:
            if r.teacher_id and m.key[0]:
                teacher.setdefault(r.teacher_id, m.key[0])
            if r.member_id and m.key[1]:
                student.setdefault(r.member_id, m.key[1])
    return {"teacher": teacher, "student": student, "group": group}

def _fid(x):
    """Render an id cleanly: raw ids arrive as floats (856752.0) — show 856752."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x

def _teacher_disp(reg, teacher_id):
    if teacher_id and reg["teacher"].get(teacher_id):
        return reg["teacher"][teacher_id]
    return f"Teacher #{_fid(teacher_id)}" if teacher_id else "(no instructor)"

def _member_disp(reg, member_id, group_id):
    """Member is either a student or a group — keep the role explicit either way."""
    if group_id:
        return reg["group"].get(group_id) or f"Group #{_fid(group_id)}"
    if member_id and reg["student"].get(member_id):
        return reg["student"][member_id]
    return f"Student #{_fid(member_id)}" if member_id else "(no member)"

def _who(teacher, member, teacher_id, member_id, group_id):
    return {"teacher": teacher, "member": member,
            "who": f"Teacher: {teacher} · Student/Group: {member}",
            "teacher_id": _fid(teacher_id), "member_id": _fid(member_id),
            "group_id": _fid(group_id)}

def _occ_who(o, reg):
    """Who/where for a single occurrence-level finding (cancelled / substitute)."""
    info = _who(_teacher_disp(reg, o.teacher_id), _member_disp(reg, o.member_id, o.group_id),
                o.teacher_id, o.member_id, o.group_id)
    info["weekday"] = _WD[o.date.weekday()]
    return info

def _label(r, m, reg):
    """Readable, filterable label for a (raw, migration) series pair. Uses template names
    when matched; otherwise resolves raw ids to names via the registry, falling back to a
    role-tagged id (e.g. 'Teacher #822622') so the party is never ambiguous."""
    s = m if m is not None else r
    if m is not None:
        teacher = m.key[0] or "(no instructor)"
        member = m.key[1] or "(no member)"
    else:
        teacher = _teacher_disp(reg, r.teacher_id)
        member = _member_disp(reg, r.member_id, r.group_id)
    wd = _WD[s.weekday] if 0 <= s.weekday < 7 else "?"
    text = f"{teacher} / {member} · {wd} {s.start}-{s.end}"
    info = _who(teacher, member,
                (r.teacher_id if r else None), (r.member_id if r else None),
                (r.group_id if r else None))
    info.update({"label": text, "weekday": wd, "start": str(s.start), "end": str(s.end)})
    return info

def _compare_pair(r, m, findings, reg):
    """Compare one matched (raw, migration) series pair and append findings."""
    if r is None:
        findings.append(Finding("error", "EXTRA_SERIES",
                                f"migration series has no raw counterpart ({_label(r, m, reg)['label']})",
                                "series", {"count": len(m.dates), "dates": _ds(m.dates),
                                           **_label(r, m, reg)}))
        return
    if m is None:
        findings.append(Finding("error", "MISSING_SERIES",
                                f"raw series not represented in migration ({_label(r, m, reg)['label']})",
                                "series", {"count": len(r.dates), "dates": _ds(r.dates),
                                           **_label(r, m, reg)}))
        return

    lab = _label(r, m, reg)
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
    matches = matcher.match_series(raw_series, mig_series)
    reg = _name_registry(edge_facts, matches)
    for r, m, _j in matches:
        _compare_pair(r, m, findings, reg)

    # Date-specific exception invariants (operate on the full occurrence sets).
    mig_live_slots = Counter(o.slot_key() for o in mig_live)
    for o in raw_occ:
        if o.kind == "cancelled" and mig_live_slots.get(o.slot_key()):
            findings.append(Finding("error", "CANCELLED_STILL_LIVE",
                                    f"cancelled raw lesson at {o.slot_key()} is live in migration",
                                    "cancellation", {"date": str(o.date), "start": str(o.start),
                                                     "end": str(o.end), "student_plan_id": o.source_id,
                                                     **_occ_who(o, reg)}))

    # A substituted lesson is only a problem if its slot is missing from the migration
    # entirely. When a permanent substitute is reassigned as the teacher (v2 model), the
    # lesson still exists as a normal occurrence — that is correct, not "lost".
    for o in raw_occ:
        if o.kind == "substitute" and not mig_live_slots.get(o.slot_key()):
            findings.append(Finding("warn", "SUBSTITUTE_DROPPED",
                                    f"substituted lesson at {o.slot_key()} is absent from migration",
                                    "substitute", {"date": str(o.date), "start": str(o.start),
                                                   "end": str(o.end), "student_plan_id": o.source_id,
                                                   **_occ_who(o, reg)}))

    raw_spids = {o.source_id for o in raw_occ}
    for e in edge_facts:
        if e.student_plan_id not in raw_spids:
            e_teacher = e.teacher_name or (f"Teacher #{e.teacher_id}" if e.teacher_id else "?")
            e_member = (e.student_name or e.group_name
                        or (f"Student #{e.student_id}" if e.student_id else "?"))
            findings.append(Finding("error", "EDGE_ORPHAN",
                                    f"edge StudentPlanID {e.student_plan_id} absent from raw",
                                    "structural",
                                    {"student_plan_id": e.student_plan_id,
                                     **_who(e_teacher, e_member, e.teacher_id, e.student_id, e.group_id)}))

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
