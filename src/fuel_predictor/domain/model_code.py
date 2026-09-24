"""The model code: how people name a model version (`M-260924-01`).

The day the model finished training, in site-local time, and its place among
the models that finished that day. Given once, when the model is registered -
trained in the app or uploaded as a package - and never recomputed, so a code
quoted in a report or next to an estimate always means the same model.
"""

from collections.abc import Iterable
from datetime import date

_PREFIX = "M-"


def model_code(finished_on: date, sequence: int) -> str:
    return f"{model_code_prefix(finished_on)}{sequence:02d}"


def model_code_prefix(finished_on: date) -> str:
    return f"{_PREFIX}{finished_on:%y%m%d}-"


def next_model_code(finished_on: date, taken: Iterable[str]) -> str:
    """The first sequence after every code already given that day."""
    prefix = model_code_prefix(finished_on)
    used = [int(code[len(prefix) :]) for code in taken if code.startswith(prefix)]
    return model_code(finished_on, max(used, default=0) + 1)
