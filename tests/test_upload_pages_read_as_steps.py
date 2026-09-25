"""The bulk pages say what to do in three numbered steps, in plain words.

Each opened with step chips, then a row of download buttons, then a paragraph
repeating the steps with the column names; the lead spoke of rows being
"dikarantina", and a button at the bottom repeated a sidebar entry.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("path", "first_action"),
    [
        ("/bahan-bakar-aktual-massal", 'href="/bahan-bakar-aktual/menunggu.xlsx"'),
        (
            "/prediksi-operasi-massal",
            'href="/api/v1/bulk-operation-predictions/template?format=xlsx"',
        ),
    ],
)
def test_a_bulk_page_is_three_steps_starting_with_its_download(
    client: TestClient, path: str, first_action: str
) -> None:
    main = client.get(path).text.split("<main ", 1)[1]

    steps = main.split('<ol class="numbered-steps">', 1)[1].split("</ol>", 1)[0]
    assert steps.count("<li>") == 3
    first_step = steps.split("<li>")[1]
    assert first_action in first_step
    assert 'type="file"' in steps.split("<li>")[3]
    # No chips restating the steps, no jargon, no sidebar entry repeated.
    assert 'class="steps"' not in main
    assert "dikarantina" not in main
    assert "Catat satu operasi saja" not in main


def test_the_actual_fuel_form_offers_the_slip_s_choices_in_the_slip_s_order(
    client: TestClient,
) -> None:
    page = client.get("/bahan-bakar-aktual").text

    choices = page.split('name="measurement_source"', 1)[1].split("</select>", 1)[0]
    assert choices.index("Meter BBM") < choices.index("Nota") < choices.index("Catatan manual")
    assert "Bukti/nota" not in choices
    # The form is one group; no fieldset box inside the card.
    assert "<legend>Hasil operasi</legend>" not in page
