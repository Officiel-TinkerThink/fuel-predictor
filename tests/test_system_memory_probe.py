"""The activation capacity check's memory probe (ADR 0010)."""

from fuel_predictor.infrastructure.system_memory_probe import SystemMemoryProbe


def test_reports_a_plausible_amount_of_available_memory() -> None:
    assert SystemMemoryProbe(safety_margin_bytes=0).available_bytes() > 0


def test_the_safety_margin_is_held_back_from_what_is_offered() -> None:
    """An activation must not be able to consume the last of the machine's memory.

    The point of the capacity check is protecting the model already serving,
    so the probe reports less than the raw figure on purpose.
    """
    raw = SystemMemoryProbe(safety_margin_bytes=0).available_bytes()
    margin = 64 * 1024 * 1024

    reserved = SystemMemoryProbe(safety_margin_bytes=margin).available_bytes()

    assert reserved <= raw - margin + 1


def test_never_reports_a_negative_amount() -> None:
    """A margin larger than available memory means 'none', not a negative number.

    A negative value would compare as less than any candidate's requirement
    and silently invert the capacity check into always-allow.
    """
    absurd_margin = 1 << 62

    assert SystemMemoryProbe(safety_margin_bytes=absurd_margin).available_bytes() == 0
