# Roadmap: What We Record, and What It Buys

## Purpose

Five levels of record-keeping for fuel prediction, from the figures captured
today to continuous measurement. Each level lets the model see something the
one below it cannot, and each is a decision about what the operation writes
down rather than a decision about modelling technique.

## The framing

Accuracy comes from the record, not from the mathematics.

Every level below uses machine learning — a model that learns from history
rather than fixed rules someone wrote down. What changes between levels is not
the technique but what the model is allowed to see. A model cannot learn that
heavy loads burn more fuel if nobody ever wrote down the weight.

This matters when presenting the plan: a regularised regression trained on
operational history *is* machine learning. What it is not is rule-based — fixed
thresholds like "five litres per site" that never improve. Starting simple does
not mean starting without a model.

---

## Level 1 — Journey totals

**Fields:** specific vehicle · vehicle type · total distance · total lifting hours

**Status:** implemented. See `20260905_17_vehicle_identity`.

The day arrives as a single lump: how far the vehicle went, how long it spent
lifting, and which truck did it.

One correction belonged at this level rather than later. `VehicleCategory` has
exactly one value, `ANGBER`, and it was being handed to the model as a feature.
A column holding the same value on every row is a constant — it carried no
information, so the model had no vehicle signal at all while appearing to have
one. The operational sheets have always named the individual unit.

Recording *which truck*, not merely that it was heavy haulage, was the cheapest
improvement available: two cranes of the same model do not consume alike once
one is older.

- **The model sees:** the scale of the day, and the habits of each unit.
- **Blind to:** the shape of the day. Two operations covering the same distance
  look identical, whether that was one long haul or eight short hops.
- **Capture cost:** none. The vehicle is already named in the source records.

This is the only level with **no waiting period**. Every other level accumulates
from the day it is switched on; vehicle identity is present throughout the
historical sheets and can be backfilled with full history behind it.

---

## Level 2 — The shape of the journey

**Fields:** *(adds)* distance per leg · activity per stop · lifting hours per stop

**Status:** implemented on the `per-stop-lifting` branch, awaiting a decision.

Instead of one total, the day is recorded as the sequence it actually was:
depart here, load there, unload at the next site, return. Two things become
visible that Level 1 cannot show.

**How many stops.** A hundred kilometres across two stops is not the same job as
a hundred across eight — every stop means braking, idling, manoeuvring and
pulling away again.

**Loaded or empty on each leg.** Once a stop is marked as loading or unloading,
the model knows whether the vehicle was carrying anything on the leg that
followed. For heavy haulage that difference is large, and it costs no extra
entry beyond what this level already asks.

- **The model sees:** journey structure, and whether the truck was working or
  running empty.
- **Capture cost:** the planner picks a location, an activity and lifting hours
  per stop, instead of one figure for the day.

**This level has a waiting period.** Per-stop history cannot be reconstructed
from past records — it accumulates only from the day it is switched on. That is
the argument for deciding sooner rather than later: the waiting is the expensive
part, not the building.

---

## Level 3 — Terrain, and the specific truck

**Fields:** *(adds)* elevation and gradient per leg · road surface class

**Status:** not started.

This level asks the operation for nothing at all. Coordinates are already stored
for more than a thousand locations, so the climb and descent on every leg can be
calculated from records that exist. For a loaded heavy vehicle, gradient is a
serious cost — a route that gains three hundred metres is not the same as a flat
one of equal length.

Surface can be treated the same way where the route is known: a graded lease
road and a sealed highway do not cost the same per kilometre.

- **The model sees:** hills, and the ground being driven over.
- **Capture cost:** none — derived from data already held.

Worth doing early precisely because it is free. It earns credibility for the
levels that do cost something.

---

## Level 4 — Load and time

**Fields:** *(adds)* hauled weight per leg · lifted mass · arrival and departure per stop

**Status:** not started.

Weight is the largest thing still missing. Fuel is close to proportional to the
mass being moved, so hauling twenty tonnes and running empty over the same route
are different jobs — and today they look identical to the model.

One distinction matters more here than it first appears, because in this
operation the two masses are frequently not the same object:

| | What it is | What it drives |
|---|---|---|
| **Hauled mass** | What rides on the vehicle | Fuel burned while moving, roughly in proportion to weight |
| **Lifted mass** | What the crane picks | Fuel burned while lifting — a separate energy path, already partly captured by lifting hours |

A Truck Crane can drive to a well pad carrying nothing, spend two hours lifting
pipe into position, and return empty: hauled mass near zero, lifted mass
substantial. A Prime Mover on the same day may haul twenty tonnes and lift
nothing. Recording a single "weight" would blur those into one confused figure.

**Time** exposes what distance hides. A vehicle waiting three hours at a site
burns fuel while the odometer stays still. Arrival and departure stamps give
idle and waiting hours directly.

- **The model sees:** the physical work done, not just the ground covered.
- **Capture cost:** real. Someone records tonnage and times. This is the level
  that genuinely changes what the operation writes down.

**On recording what the load is.** Weight carries most of the effect. The object
itself matters only at the margins — bulky loads meet more air resistance,
awkward ones force lower speeds. Record a coarse class of four or five
categories, not the specific item: at this data volume a detailed list fragments
the history into slices too thin to learn anything from.

---

## Level 5 — Continuous measurement

**Fields:** *(adds)* fuel-flow sensors · GPS traces · engine hours

**Status:** not started.

Instrumentation rather than paperwork. The existing fuel-stick records already
point in this direction — the difference is that measurement becomes continuous
and automatic rather than written down once per day.

This is where prediction stops being checked against what was recorded and
starts being checked against what was measured.

- **Capture cost:** hardware, fitting, and a data pipeline.

---

## How each level is judged

**Every field we ask the operation to record, we later prove or remove.**

A new field is an experiment, not a permanent addition to the paperwork. Once
enough history has accumulated, each one is tested: does the model predict
measurably better with it than without it? If it does, the field stays and we
can say what it was worth in litres. If it does not, we stop asking for it.

Cargo class at Level 4 is the clearest candidate for that review — worth
collecting because it is cheap to write down, and worth dropping if weight turns
out to explain everything it does.

Two further rules:

- **Levels are cumulative but independent.** Each keeps working if the next is
  never adopted. Stopping at Level 3 leaves a functioning, improved model — not
  a half-finished one.
- **Every level is compared the same way:** against the level below it, on
  operations the model has never seen, measured in litres of error. A level that
  does not beat its predecessor is not adopted.

---

## What this plan does not promise

**New fields take months to pay.** A feature only helps once there is history
behind it. Recording weight from next month means a model that can use weight
several months later. The waiting cannot be compressed, which is why the choice
of level is worth taking early.

**Data volume sets a ceiling.** Several hundred recorded journeys across the
fleet. Enough for the levels described here; not enough for the very large
models used elsewhere, and promising those would be a commitment to walk back.

**One model, not one per vehicle.** Vehicle type and identity enter as features
rather than splitting into a model per unit. Per-unit history is too thin to
divide, and one model shares what the units have in common. A truck new to the
fleet should start at its type's average and move toward its own behaviour as
journeys accumulate.

**The target itself limits accuracy.** The model currently learns from fuel that
was *prepared* — a person's estimate, possibly already a rule of thumb. Training
on fuel *actually consumed*, which the system already records, would plausibly
matter more than any single level above. It runs in parallel and blocks nothing.
See [ADR 0002](../adr/0002-prepared-and-actual-fuel-are-distinct.md).

**Reported in litres, not statistics.** Progress is stated as average error in
litres and shortages avoided — numbers the operation can argue with, rather than
scores only the engineering team can read.

---

## Summary

| Level | What gets recorded | What the model can finally see | Cost to the operation |
|---|---|---|---|
| 1 | Specific vehicle, type, total distance, total lifting hours | Scale of the day, and each truck's own habits | None — already in the records |
| 2 | Distance, activity and lifting hours per stop | Stop count; loaded versus empty running | A few fields per stop |
| 3 | Nothing new — derived from coordinates already held | Gradient and ground conditions | None |
| 4 | Hauled weight, lifted mass, arrival and departure times | Physical work done; waiting and idling | Real — new records at each stop |
| 5 | Sensor and GPS measurement | Consumption as it happens | Hardware and integration |

The order is deliberate: what is already recorded, then what is free to derive,
then what must be newly written down. Cost to the operation rises with each
level, and so does what the model is able to explain.

## Open questions

These need answers from the operation, not from engineering:

1. **Is "Prime Mover" one truck or several?** "Truck Crane 01" and "02" are
   clearly individual units. If "Prime Mover" covers several trucks sharing a
   sheet, there are fewer distinct units than it appears and the per-unit effect
   is weaker.
2. **Do the fuel figures attach to a truck or to a day?** If two vehicles ever
   work one operation and the litres are recorded jointly, per-vehicle
   attribution is muddier than the sheet layout suggests.
3. **Is Level 2 confirmed?** It is built and waiting. Because its history cannot
   be backfilled, the cost of deciding late is measured in months.
