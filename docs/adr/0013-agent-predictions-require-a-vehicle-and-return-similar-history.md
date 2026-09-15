# ADR 0013: Agent predictions require a named vehicle and return similar history

## Status

Accepted

## Context

The first MCP demo answered `predict_fuel` for a vehicle category alone. That matched the MVP's
feature contract at the time, but the individual vehicle has since become a model feature
(`baseline-v2`): two cranes of the same model do not consume alike, and the fleet catalog and its
aliases now exist precisely so the unit can be named.

The client's request for the agent flow is two-fold. A planner asks, in their own words, for a
fuel recommendation for a specific unit on a specific route ("mobilisasi pipa, Truck Crane 01,
Pool Limau ke SP II"). The agent must answer with the recommendation and its details, and show
past operations that resemble the request, so the planner can judge the number against what that
crane actually needed before.

Two things follow that a vehicle-less contract cannot give:

- Without the unit, the estimate is a fleet average presented as a recommendation for one crane.
- Without the unit, there is nothing to find similar history *by*; category is one value.

## Decision

### The vehicle is required for an agent prediction

`predict_fuel` requires `vehicle`. The written name is resolved against the vehicle catalog,
including the aliases the planner's sheets use, and case, spacing, punctuation and numeral style
are ignored. A name that does not resolve is a tool error that lists the nearest catalog entries;
the tool never picks one on the agent's behalf, because a near-miss becomes a real operation on
the wrong unit. Stops in `stop_sequence` are resolved the same way against the location catalog.

This applies to the MCP surface only. The web form, REST API and bulk template keep `vehicle`
optional: bulk uploads and operations recorded before the fleet was identified still exist there,
and requiring the unit on those paths is a separate decision.

### Similar history travels with the recommendation

The prediction response carries `similar_operations`: past operations ranked by same vehicle,
then same kind of machine (vehicle group), then same category; within a tier by same activity
mode; then by nearest distance and lifting hours. Both places the system keeps history are merged:
imported dataset rows (prepared fuel, the data the active model learned from) and operations
recorded through the app or an agent (their stops, the estimate given at the time, and the actual
fuel once entered). Prepared fuel and actual fuel stay distinct fields (ADR 0002).

History is attached to `predict_fuel` rather than left to a separate tool because a second call
the agent has to remember to make is one the planner will sometimes not see the result of. A
standalone `find_similar_operations` exists for browsing without creating an operation, and
`list_vehicles`, `search_locations` and `estimate_route_distance` let the agent confirm names and
the route before it commits.

The history is shown, not used: nothing in it adjusts the estimate. Similar rows are evidence for
the planner; the model remains the only source of the number.

### Name resolution and ranking are application logic

Resolution (`application/catalog_resolution.py`) and ranking (`application/similar_operations.py`)
live in the application layer with a port for where history comes from. The MCP adapter only
translates arguments and results. A later chat-style page uses the same rules rather than
reimplementing them.

## Consequences

- An agent that used the earlier `vehicle_category`-only contract must now supply `vehicle`;
  `vehicle_category` defaults to `ANGBER`, the only value.
- Every `predict_fuel` still records a daily operation (as before). The operation being planned is
  excluded from its own similar history.
- Two catalog names that differ only in case ("WORKSHOP RAM" / "Workshop RAM") are reported as
  ambiguous rather than resolved; the source sheet should be cleaned, but the tool must not guess
  in the meantime.
- Recorded history is read from the newest few thousand operations; an installation that outgrows
  that will need the search pushed further into SQL.
