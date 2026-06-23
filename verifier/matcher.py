from __future__ import annotations
from collections import Counter, defaultdict
from .models import Series

def slot_multiset(occurrences):
    return Counter(o.slot_key() for o in occurrences)

def diff_multisets(raw_ms, mig_ms):
    return {"missing_in_migration": raw_ms - mig_ms,
            "extra_in_migration": mig_ms - raw_ms}

def build_series(occurrences, side):
    groups = defaultdict(list)
    for o in occurrences:
        if side == "raw":
            key = (o.teacher_id, o.member_id, o.group_id, o.start, o.end)
        else:
            key = (o.teacher, o.member, o.start, o.end)
        groups[key].append(o)
    out = []
    for key, occs in groups.items():
        dates = frozenset(o.date for o in occs)
        first = min(dates)
        sample = occs[0]
        open_ended = any(o.open_ended for o in occs)
        repeat_until = None if open_ended else max(dates)
        out.append(Series(key=key, dates=dates, start=sample.start, end=sample.end,
                          weekday=first.weekday(),
                          teacher_id=sample.teacher_id, member_id=sample.member_id,
                          group_id=sample.group_id, open_ended=open_ended,
                          repeat_until=repeat_until))
    return out

def infer_cadence_days(dates):
    """Cadence = the MINIMUM gap (in days) between consecutive sorted dates; None if <2
    dates. Minimum (not mode) so a weekly series with a cancelled/missing week — which
    leaves a 14-day hole — is still correctly read as weekly (min gap 7)."""
    ds = sorted(set(dates))
    if len(ds) < 2:
        return None
    return min((ds[i + 1] - ds[i]).days for i in range(len(ds) - 1))

def _jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)

def match_series(raw_series, mig_series):
    buckets = defaultdict(lambda: {"raw": [], "mig": []})
    for s in raw_series:
        buckets[(s.weekday, s.start, s.end)]["raw"].append(s)
    for s in mig_series:
        buckets[(s.weekday, s.start, s.end)]["mig"].append(s)

    pairs = []
    for _, grp in buckets.items():
        candidates = []
        for r in grp["raw"]:
            for m in grp["mig"]:
                candidates.append((_jaccard(r.dates, m.dates), r, m))
        candidates.sort(key=lambda t: t[0], reverse=True)
        used_r, used_m = set(), set()
        for j, r, m in candidates:
            if id(r) in used_r or id(m) in used_m:
                continue
            pairs.append((r, m, j))
            used_r.add(id(r)); used_m.add(id(m))
        for r in grp["raw"]:
            if id(r) not in used_r:
                pairs.append((r, None, 0.0))
        for m in grp["mig"]:
            if id(m) not in used_m:
                pairs.append((None, m, 0.0))
    return pairs
