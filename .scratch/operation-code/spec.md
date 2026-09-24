# Operation code: an ID a non-technical operator can write down and type back

Status: in-review

Written 2026-09-23 after a design conversation with the product owner.

## Problem

Actual fuel is recorded against a daily operation, days or weeks after the operation was
planned. The only handle the operator has today is `OPR-` plus 32 hex characters. Nobody can
write that on a fuel slip, read it back correctly, or tell from it which job it was, so when the
weekly or monthly actual-fuel sheet is filled in, values land on the wrong operation or are never
recorded, and the model never learns from the day.

Actual fuel is measured **per vehicle per job**, so a per-operation handle is the right grain.

## Decisions (agreed with the product owner)

1. **Every newly planned operation gets an operation code** built from what the operator knows
   at planning time: when it was created, in site-local time, and which vehicle.

   ```
   260923-0914-VT01        yymmdd-hhmm-<vehicle mark>
   260923-0914-VT01-2      the same vehicle again within the same minute
   260923-0914             no vehicle named (older API callers)
   ```

2. **The time is the creation time** (`created_at`), not a separate "day of the job". The
   operator notes the code when the prediction is generated.
3. **Site-local time.** `created_at` stays stored in UTC; the code is formed in the site time zone,
   a new setting `FUEL_PREDICTOR_SITE_TIMEZONE` (default `Asia/Jakarta`). Screens show times in the
   same zone, so the time printed in the code matches the time shown next to it.
4. **Accidental duplicates are expected and harmless.** A double submission produces a second
   operation within seconds; it gets the `-2` suffix, and the operator records actual fuel against
   only one. Marking the leftover as a duplicate is a follow-up, not part of this change.
5. **The vehicle mark is short**: words written in capitals or containing digits are kept whole,
   other words shrink to their initial — `VT 01` → `VT01`, `Truck Crane 01` → `TC01`,
   `Oil Field Truck` → `OFT`, `Wheel Loader Forklift` → `WLF`.
6. **The code is stored, never recomputed.** It is fixed at creation. A catalog rename or a
   time-zone change never changes a code the operator already wrote down.
7. **`OPR-…` stays the primary key.** The code is a second, unique identifier for people.
   Everywhere an operator records actual fuel (form, API, spreadsheet import), either the code or
   the `OPR-…` id is accepted. Typed codes are matched ignoring case and spaces.
8. **Existing operations get a code** by backfill from their stored `created_at` (in
   `Asia/Jakarta`). Imported historical rows (`IMPR-…`) have no creation time and are never waiting
   for actual fuel, so they get none.

> **Revised 2026-09-24:** the vehicle part of the code now names group, type and unit —
> `260924-0914-VT-P410-VT01` — from codes held in the vehicle catalog. See
> `.scratch/fleet-taxonomy/spec.md` and ADR 0016.

## Out of scope

- Marking or cancelling a duplicate operation so it leaves the "waiting for actual fuel" list.
- A pre-filled download of the operations still waiting for actual fuel.
- A separate "date the job runs" field.

## Issues

- `issues/01-generate-and-store-the-operation-code.md`
- `issues/02-record-actual-fuel-by-operation-code.md`
- `issues/03-show-the-code-and-site-local-times.md`
