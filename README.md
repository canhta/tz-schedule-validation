# Schedule Migration RRULE Verifier

Independent, black-box verifier for TeacherZone schedule migrations. Given an org's raw
occurrence export and its converted RRULE template (with edge-case sheet), it reconstructs the
schedule from the migration output and reconciles it against the raw data — proving whether the
portal converter preserved the schedule. Reusable across all orgs (config-driven, no
org-specific data in code).

## Install

```bash
pip install -r requirements.txt
```

## Run

Single org (JSON report to stdout; exit 0=PASS, 2=NEEDS_REVIEW, 1=FAIL):

```bash
python -m verifier.cli \
  --raw  Paper_Moon_Music_Raw_Data.xlsx \
  --template Paper_Moon_Music_Converted_Template.xlsx \
  --org "Paper Moon Music"
```

Add a standalone HTML diff visualization (open in any browser — verdict banner, color-coded
slot diff, findings table):

```bash
python -m verifier.cli --raw RAW.xlsx --template TPL.xlsx --org NAME --html report.html
```

Write a developer defect report (.xlsx — one row per issue with instructor/student/day/time,
the specific dates/values, and a fix hint):

```bash
python -m verifier.cli --raw RAW.xlsx --template TPL.xlsx --org NAME --defects defects.xlsx
```

Fleet mode (a directory of `<org>/` subdirs each with `*_Raw_Data.xlsx` +
`*_Converted_Template.xlsx`; prints a roll-up):

```bash
python -m verifier.cli --fleet ./all_orgs
```

### Upload UI (validate two files in the browser)

No CLI needed — start the local upload server, open it, and drop in the two xlsx files:

```bash
python -m verifier.server            # http://localhost:8000
python -m verifier.server --port 9000
```

Pure Python stdlib (no extra dependencies). The interactive report opens in the same tab:
verdict banner, summary cards, filter chips per finding type, severity toggles, a search box,
and a collapsible slot diff.

## How it works

1. **Expand** template RRULEs into occurrences over the raw data window.
2. **Apply edges** — cancellations, substitutes (split-aware), only-this adjustments.
3. **Normalize raw**, auto-detecting and removing the UTC→local timezone offset.
4. **Reconcile** per series: rule-equivalence for open-ended series, exact bijection for finite
   series, plus date-specific exception invariants (cancelled-still-live, substitute-lost,
   edge-orphan, double-count).

See `docs/superpowers/specs/` for the design (incl. real-data discoveries) and
`docs/superpowers/plans/` for the implementation plan.

## Test

```bash
pytest -q
```

## Finding codes

| Code | Meaning |
|------|---------|
| `MISSING_SERIES` | A raw enrollment has no counterpart in the migration. |
| `EXTRA_SERIES` | A migration series has no raw counterpart (see spec open question). |
| `RULE_FLAG_MISMATCH` | Open-ended vs end-dated flag differs between raw and template. |
| `RULE_MISSING_DATE` | The rule fails to reproduce a raw occurrence. |
| `RULE_EXTRA_IN_WINDOW` | The rule generates occurrences within raw's horizon that raw lacks. |
| `CADENCE_MISMATCH` | Inferred cadence (weekly/bi-weekly) differs. |
| `MISSING` / `EXTRA` | Finite-series occurrence missing / extra. |
| `CANCELLED_STILL_LIVE` | A cancelled raw lesson is live in the migration. |
| `SUBSTITUTE_LOST` | A raw substitute is not represented. |
| `EDGE_ORPHAN` | An edge row references a `StudentPlanID` absent from raw. |
| `DOUBLE_COUNT` | A slot has both a normal and an exception occurrence. |
