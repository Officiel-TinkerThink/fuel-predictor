# ADR 0016: An operation code is the identifier operators write down

## Status

Proposed

## Context

Actual fuel is recorded against a daily operation (ADR 0002), days or weeks after the operation
was planned, usually from a weekly or monthly sheet. The only handle an operator had was the
operation id, `OPR-` plus 32 hex characters. It cannot be copied onto a fuel slip, read back
correctly, or recognised as "the crane job on Tuesday", so actual fuel landed on the wrong
operation or was never recorded, and the model never learned from the day.

Actual fuel is measured per vehicle per job, so a per-operation handle is the right grain. The
operators are not technical.

## Decision

Every operation someone plans gets an **operation code** when it is created:

```
260924-0914-VT-P410-VT01     yymmdd-hhmm-<vehicle code>
260924-0914-VT-P410-VT01-2   the same vehicle again within the same minute
260924-0914-VT-VT14          a unit whose type is only its group
260924-0914                  no vehicle named
```

- **Time is the creation time, in site-local time.** `created_at` stays stored in UTC; the code
  is formed in the zone named by `FUEL_PREDICTOR_SITE_TIMEZONE` (default `Asia/Jakarta`), and
  every screen shows times in that zone, so the time in a code matches the time printed beside it.
- **The vehicle code names group, type and unit** (revised 2026-09-24 at the owner's request):
  `VT-P410-VT01` is group Vacuum Truck, type Scania P410 6X6, unit VT 01. Group and type codes are
  held in the vehicle catalog next to their names (`kode_grup`, `kode_tipe`), one code per group
  and per type, so the owner decides them. The unit's mark is derived from its name: a word in
  capitals, with a digit, or of at most two letters is kept whole, any other word shrinks to its
  initial (`Truck Crane 01` → `TC01`, `Oil Field Truck` → `OFT`). A part the catalog does not code
  is left out; a vehicle the catalog does not know is its mark alone. The Armada page lists every
  unit's code.
- **Unique, with the lowest free suffix from 2.** The same unit twice in one minute is nearly
  always a double submission; the operator records actual fuel against one of them. A concurrent
  insert that takes the chosen code is retried with the next suffix.
- **Stored, never recomputed.** A catalog rename, a re-typing of the fleet (ADR 0015) or a
  time-zone change never alters a code someone already wrote down.
- **A second identifier, not a new key.** `operation_id` stays the primary key and the foreign key
  everywhere. Wherever a person names an operation to record actual fuel (form, API path,
  spreadsheet import), either the code or the `OPR-…` id is accepted, ignoring case and spaces.
- **Existing planned operations are backfilled** from their stored `created_at`. Imported history
  (`IMPR-…`) has no creation time and is never waiting for actual fuel, so it has no code.

## Consequences

- An operator notes one short, meaningful code at prediction time and can reconstruct most of it
  from their own log if the note is lost.
- The code carries the type and group as they were when it was issued. If the owner later
  re-types a unit (ADR 0015), older codes keep the old type code and new ones get the new; both
  still find their operation, because a code is looked up, never parsed.
- The code is longer (up to about 30 characters). The owner chose completeness over brevity; the
  estimate spells out what each part means, and the copy button and the result CSV spare most
  hand copying.
- Operations that existed before vehicle codes keep the unit-only code the backfill gave them.
- Operations planned in bulk carry the upload time, not the day each job runs; the result download
  pairs every code with its source row.
- A leftover duplicate stays on the "waiting for actual fuel" list until a way to mark it as a
  duplicate exists.
