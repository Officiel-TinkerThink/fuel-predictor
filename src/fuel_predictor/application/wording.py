"""Numbers in messages written by the application, as the pages print them.

The pages show litres with up to two decimals, a comma and no trailing zeros
(6,66 L; 21 L). Messages built here used one decimal, so the model page said
the active model missed by "6,7 L" right above a card saying 6,66 L.
"""


def liters(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " L"


def percent(share: float) -> str:
    return f"{share * 100:.0f}%"
