"""Available-memory probe for the activation capacity check (ADR 0010)."""

from collections.abc import Callable
from dataclasses import dataclass, field

import psutil


def _system_available_bytes() -> int:
    return int(psutil.virtual_memory().available)


@dataclass(frozen=True, slots=True)
class SystemMemoryProbe:
    """Reports memory available for loading a candidate.

    Reports *available* rather than *free*: free memory excludes reclaimable
    page cache, so on a healthy server it reads far lower than what a new
    allocation could actually obtain, and using it would reject activations
    that would have been perfectly safe.

    `safety_margin_bytes` is held back so an activation cannot consume the
    last of the machine's memory and leave nothing for the request currently
    being served — the whole point of the capacity check is to protect the
    model already running.
    """

    safety_margin_bytes: int = 128 * 1024 * 1024
    # Injectable so the margin arithmetic can be tested against a fixed
    # reading. Testing it against two live samples cannot work: available
    # memory moves between the calls, so the comparison is really asserting
    # that nothing else on the machine allocated or freed anything in between.
    read_available_bytes: Callable[[], int] = field(default=_system_available_bytes)

    def available_bytes(self) -> int:
        usable = self.read_available_bytes() - self.safety_margin_bytes
        return max(0, usable)
