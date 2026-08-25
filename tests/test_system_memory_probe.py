"""The activation capacity check's memory probe (ADR 0010)."""

from fuel_predictor.infrastructure.system_memory_probe import SystemMemoryProbe

_GIB = 1024 * 1024 * 1024


def _probe(available: int, margin: int) -> SystemMemoryProbe:
    return SystemMemoryProbe(
        safety_margin_bytes=margin, read_available_bytes=lambda: available
    )


def test_reports_a_plausible_amount_of_available_memory() -> None:
    """The one test that reads the real machine, and it asserts only a sign."""
    assert SystemMemoryProbe(safety_margin_bytes=0).available_bytes() > 0


def test_the_safety_margin_is_held_back_from_what_is_offered() -> None:
    """An activation must not be able to consume the last of the machine's memory.

    The point of the capacity check is protecting the model already serving,
    so the probe reports less than the raw figure on purpose.

    Against a fixed reading, deliberately. An earlier version compared two live
    samples and so failed whenever anything else on the machine freed memory
    between them — it was really asserting that the host was idle.
    """
    probe = _probe(available=8 * _GIB, margin=128 * 1024 * 1024)

    assert probe.available_bytes() == 8 * _GIB - 128 * 1024 * 1024


def test_a_zero_margin_offers_the_whole_reading() -> None:
    assert _probe(available=4 * _GIB, margin=0).available_bytes() == 4 * _GIB


def test_never_reports_a_negative_amount() -> None:
    """A margin larger than available memory means 'none', not a negative number.

    A negative value would compare as less than any candidate's requirement
    and silently invert the capacity check into always-allow.
    """
    assert _probe(available=1 * _GIB, margin=8 * _GIB).available_bytes() == 0
    assert SystemMemoryProbe(safety_margin_bytes=1 << 62).available_bytes() == 0


def test_a_margin_exactly_equal_to_available_memory_offers_nothing() -> None:
    """The boundary the capacity check turns on, so it is pinned explicitly."""
    assert _probe(available=2 * _GIB, margin=2 * _GIB).available_bytes() == 0


def test_the_default_probe_reads_the_real_machine() -> None:
    """The injection point must not quietly become a stub in production.

    Only that the default reads something plausible from the host — the two
    values cannot be compared, because the quantity moves between the calls.
    """
    assert SystemMemoryProbe(safety_margin_bytes=0).read_available_bytes() > 0
