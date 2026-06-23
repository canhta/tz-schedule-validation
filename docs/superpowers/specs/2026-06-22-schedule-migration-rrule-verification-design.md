# Schedule Migration RRULE Verification Harness — Design

**Date:** 2026-06-22
**Status:** Approved (design phase)
**Author:** Migration team + Claude

## Problem

TeacherZone is migrating per-org schedule data. A portal function converts **raw
materialized occurrences** into an **import template** built around recurrence
rules (RRULE-style: `Repeat`, `Repeat Days`, `Repeat Until`) plus a separate
**edge-case sheet** for exceptions (cancellations, substitutions, etc.).

The portal converter is **not trusted** — we have no way today to confirm a
conversion is faithful. We need an **independent, black-box verifier** that, given
an org's `(raw, template)` pair, proves whether the conversion preserved the
schedule. It must be **reusable across ~200 orgs**, so it cannot hardcode
org-specific data (names, IDs, single-org quirks).

## Inputs (reverse-engineered from the Paper Moon fixture)

### Raw data (`Trang tính1`, 3,696 rows) — ground truth
One row per **occurrence** (`StudentPlanID`), a forward-looking materialized
snapshot (Jun→Nov 2026). Speaks in **IDs**. Key fields:

- Identity/series: `StudentPlanID`, `PlanID`, `RefScheduleID`,
  `StudentScheduleReferenceID`, `GroupID`, `UserType`
- Time: `StartTime`, `EndTime`
- Entities: `TeacherID`, `SubstituteTeacherID`, `StudentID`, `RoomID`
- Status: `StatusID` (1/3/5), `AttendanceStatusID` (3 = cancelled),
  `BankStatusID`, `BankedDate`
- Recurrence flags: `NoEndDateID` (open-ended; 3547/3696), `EndBy` (finite; 47),
  `IsOnlyThis`, `MultipleDays`
- Other (empty in this org, present for fleet): `TimeOffSet`, `RateTypeID`

### Converted template, sheet `Schedule Import Template` (902 rows) — migration output
One row per **recurrence rule**. Speaks in **names**. Key fields:
`Start Date`, `Start Time`, `End Time`, `Location`, `Instructor(s)`,
`Member(s)`, `Classes`, `Repeat` (Weekly 887 / Bi-weekly 2 / Monthly 1 /
blank 12), `Repeat Days`, `Repeat Until` (present only 55/902 — **847 are
open-ended**).

### Converted template, sheet `Edge-case schedules` (314 rows) — exception layer
The **bridge between the two files**: every row joins to raw via `StudentPlanID`
(314/314 matched) **and** carries both IDs and names
(`TeacherID`+`TeacherName`, `GroupID`+`GroupName`, `StudentID`+`StudentName`).
Edge taxonomy (observed): `Cancelled`, `Substitute`, `Adjusted (Only This),
Substitute`, `Cancelled, Substitute`. Flag columns: `IsCancelled`, `IsBanked`,
`IsRestored`, `IsRestore`, `IsOnlyThis`, `IsAdjustedOnlyThis`,
`IsSubstitutePrivate`, `IsSubstituteFollowing` (278/314 = Yes — dominant case),
`IsSubstituteGroup`, `IsSupersededFollowing` (30), `BankStatus`, `BankLessonID`,
`AtTheMomentBank`, `RestoredFromPlanID`, `RestoredToPlanID`.

**Note on fleet generality:** Paper Moon does not exercise bank lessons, restores,
multi-day series, or timezone offsets (those columns are empty). The harness must
still implement and check them, because other orgs will exercise them.

## Verification model: "expand & reconcile"

The verifier is an **independent re-implementation of the inverse transform**. It
never calls the portal converter.

1. **Expand** each template row's RRULE into concrete occurrences
   `(date, start, end, instructor, member/class, location, room)`, bounded to the
   org's data window.
2. **Apply the edge layer**: drop/mark cancelled occurrences; swap teacher on
   substitute occurrences (split-aware for "following"); apply only-this
   adjustments; account for bank/restore.
3. **Normalize raw** into the same occurrence shape, classifying in-scope vs
   out-of-scope rows.
4. **Diff bidirectionally** (raw→migrated and migrated→raw) and run the invariant
   suite → emit findings.

The headline result per org: *does `(template ⊕ edge)` reproduce raw,
occurrence-for-occurrence?*

### Scope & window decisions (checked explicitly, not assumed)

- **Expansion window** for open-ended rules: `[min, max]` of that org's raw dates.
- **In-scope raw rows**: driven by `AttendanceStatusID` / `StatusID` / bank flags
  (active/live lessons), not guessed. Out-of-scope rows (cancelled, banked) are
  reconciled against the edge layer, not the live expansion.

## Matching strategy (name↔ID crux)

Template speaks names, raw speaks IDs, and we cannot assume a complete lookup
table per org. Three layers, each degrading gracefully:

- **Layer A — Timeslot multiset reconciliation (zero external data, always runs).**
  Bucket both sides by `(weekday, start_time, end_time, date)` and compare the
  multiset (counts). Pure datetime/duration — shared by both files. Catches
  missing/extra occurrences, wrong span, wrong day, wrong end-date. Org-agnostic
  backbone.

- **Layer B — Structural series matching (zero external data, per-series
  diagnostics).** Within each timeslot, group raw into series by
  `(TeacherID, StudentID/GroupID)` and template into series by
  `(Instructor, Member/Class)`, each producing a date-set. Bipartite-match
  raw-series ↔ template-series by date-set fingerprint, **inferring the name↔ID
  correspondence as a byproduct**. Enables "this series is short by 3 weeks".

- **Layer C — Entity name resolution (uses edge-sheet bridge + optional lookup
  tables).** The edge sheet already provides partial `TeacherID→name`,
  `GroupID→name`, `StudentID→name`. Where resolvable, confirm Layer B's inferred
  matches and label findings with real names. Supplying per-org lookup tables
  later gives total coverage. **The verifier is correct without Layer C.**

Property: **A and B need only the two files**, so the harness runs on all 200 orgs
out of the box; C improves precision and report readability.

## Critical scheduling invariants (the core value)

Each invariant emits findings independently. Anything unclassifiable → the
**unreconciled** bucket (never assumed correct).

### Tier 1 — money & operational integrity
1. **Conservation (bijection).** Every in-scope raw occurrence maps to exactly one
   migrated occurrence and vice-versa. Catches lost lessons *and*
   duplicates/double-bookings. **Master invariant.**
2. **Bank-lesson balance.** Per student, banked-but-unredeemed count
   (`BankStatusID`/`BankLessonID`/`AtTheMomentBank`) preserved; a banked lesson is
   never also a live occurrence. (Lost banks = lost paid credits.)
3. **Cancellation honored.** `AttendanceStatusID=3` / `IsCancelled` occurrences are
   absent or marked in the migrated set — never live/billable.
4. **Substitute correctness — split-aware.** For
   `IsSubstituteFollowing`/`IsSupersededFollowing`: the series splits at the right
   date, the substitute owns occurrences from the split forward, the original owns
   those before, and nothing drops at the seam. One-off substitutes
   (`IsSubstitutePrivate`/only-this) change exactly one date.

### Tier 2 — schedule fidelity
5. **Recurrence integrity.** Day-of-week, start/end time, **duration**, cadence
   (weekly/bi-weekly/monthly — never silently coerced), multi-day series
   (`MultipleDays`), and **open-ended-vs-end-by flag**
   (`NoEndDateID`/`EndBy` ↔ `Repeat Until`).
6. **DST / wall-clock stability** (`TimeOffSet`). A 7:00 PM lesson stays 7:00 PM
   across DST boundaries in the expanded series.
7. **Restore integrity.** `RestoredFromPlanID`/`RestoredToPlanID` never produce a
   double-counted lesson.

### Tier 3 — attribution
8. **Entity correctness.** Right teacher, room, and — for groups — complete
   membership (no member dropped or duplicated; `GroupID`/`UserType`).

### Structural invariants (always)
- Every edge `StudentPlanID` exists in raw (no orphan edge rows).
- No raw occurrence is both expanded-as-normal *and* listed as an edge exception
  (no double-count).
- `template-expanded ⊕ edge-adjustments == raw-in-scope` as multisets.

## Reusability across 200 orgs

- **Config-driven.** All org-specific knowledge (raw/template column names, status
  code meanings, date formats) lives in a schema/config map. No org-specific logic
  in code. Paper Moon is the reference fixture, not a special case.
- **Schema guard.** A column-presence/shape check runs first and fails fast if an
  export doesn't fit the expected schema — a malformed input never yields a false
  "all good".

## Reporting

- **Per-org report** (machine-readable JSON + human summary):
  - **Verdict**: PASS / FAIL / NEEDS-REVIEW, master-invariant result on top.
  - **Reconciliation summary**: matched / missing-in-template / extra-in-template /
    mismatched-attributes / unreconciled counts.
  - **Findings**: severity, the specific occurrence(s)/series, raw vs migrated
    values, and which layer/invariant caught it.
  - **Coverage note**: how much was resolved by name (C) vs inferred (B) vs
    timeslot-only (A) — calibrates trust in a clean result.
- **Fleet roll-up** across all 200 orgs: org, verdict, finding counts, for triage.
- **Standalone HTML visualization** (lightweight, no frontend toolchain): the verifier
  emits a single self-contained `report.html` (inline CSS/JS, no server, no build step)
  via `--html`. It renders the verdict banner, summary, a **color-coded slot diff table**
  (matched / missing-in-migration / extra-in-migration / substitute / cancelled), and the
  findings table. This is the "see and compare original vs converted, highlight the diff"
  view — chosen over a React app for speed-to-build and zero-dependency deployment.

## Architecture

Small, single-purpose, independently testable modules:

- `schema/config` — per-org-type column maps & code meanings.
- `loaders` — raw / template / edge → normalized records.
- `rrule_expander` — template row → occurrences (inverse engine; uses
  `dateutil.rrule`).
- `edge_applier` — apply exceptions (cancel / substitute-split / only-this /
  bank / restore) to the expanded set.
- `matcher` — Layers A / B / C.
- `reconciler` — bidirectional diff + invariant suite.
- `reporter` — JSON + human summary + fleet roll-up.

**Language:** Python (data is openpyxl-friendly; `python-dateutil`'s `rrule`
gives battle-tested expansion instead of hand-rolled date math).

## Testing

- **Unit tests per module** with tiny synthetic fixtures where expected
  occurrences are hand-computed: a known 3-week weekly series, an open-ended
  series bounded by window, one cancelled, one one-off substitute, one
  following-substitute (series split), a bi-weekly, a banked/redeemed pair, a DST
  crossing. These let us trust the verifier itself.
- **End-to-end** on the Paper Moon `(raw, template)` pair.

## Real-data discoveries during implementation (Paper Moon)

Running the harness on the real export revealed three semantics the initial model missed.
All three generalize to the 200-org fleet:

1. **Raw is a forward snapshot, not a full materialization.** Occurrences taper from
   ~499/week (mid-June) to ~1/week (November); avg ~8.7 occurrences per series even though
   847/902 rules are open-ended. Exact occurrence bijection over the global window therefore
   invents thousands of phantom occurrences. **Fix:** for open-ended series, compare *rule
   parameters* (weekday/time/cadence/open-ended flag) and require raw ⊆ rule within raw's own
   horizon — the tail is ignored. Finite series still use exact bijection.

2. **Raw `StartTime` is UTC; the template uses local clock time.** A constant offset (480 min
   / 8 h, i.e. UTC-8 / Pacific) aligns 99.9% of occurrences (3692/3696); the 0.1% residual are
   DST-boundary occurrences. **Fix:** auto-detect the modal offset per org and normalize raw to
   local (shifting both time *and* date/weekday) before matching. Reported as
   `coverage.tz_offset_minutes`.

3. **OPEN QUESTION — series-identity granularity.** Template carries ~637 instructor+member
   series; raw carries ~432 (raw's natural enrollment key ≈ `StudentScheduleReferenceID`; 129
   group rows have `StudentID=0`). ~322 template series have *zero* materialized lessons in the
   raw snapshot, surfacing as `EXTRA_SERIES`. Whether that is a real defect (phantom schedules)
   or expected (enrollments not yet scheduled in this export) needs a product decision before
   the harness can classify it correctly. Currently flagged as `EXTRA_SERIES` (error) pending
   that decision.

### Current Paper Moon result
Verdict FAIL with 666 findings: `EXTRA_SERIES` 446 (see open question above),
`RULE_MISSING_DATE` 160, `SUBSTITUTE_LOST` 20, `CANCELLED_STILL_LIVE` 12, `RULE_FLAG_MISMATCH`
5, `RULE_EXTRA_IN_WINDOW` 7, `CADENCE_MISMATCH` 3. 419/427 raw series matched. These are
genuine signals for the migration team to investigate, not harness artifacts.

## Out of scope (for now)

- Payment-plan / rate migration correctness (`RateTypeID`, `Rate`, template
  `Payment Plan`) beyond what bank-balance touches.
- Verifying the portal converter's internals (black-box only).
