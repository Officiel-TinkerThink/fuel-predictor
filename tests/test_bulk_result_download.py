"""The bulk prediction result can be taken away as a file.

The result page showed a table and nothing else: a planner who uploaded a
sheet of forty operations got forty rows on screen and had to copy them out
by hand. The page now offers the accepted rows as a CSV - the estimate next
to the source row it came from - built into the page itself so nothing has
to be stored server-side for a second request.
"""

import re
from html import unescape
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline

_SHEET = (
    "Kategori ANGBER (wajib),Mode Aktivitas (wajib),Jam Lifting (opsional),"
    "Jarak Total (km) (wajib),Sumber Jarak (wajib),Urutan Pemberhentian (opsional)\n"
    "ANGBER,transport,,20,manual,\n"
    "ANGBER,lifting,0,25,manual,\n"
)


def test_result_page_offers_the_accepted_rows_as_csv(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        page = client.post(
            "/prediksi-operasi-massal",
            files={"file": ("rencana.csv", _SHEET.encode(), "text/csv")},
        )

    assert page.status_code == 201, page.text
    marker = 'href="data:text/csv;charset=utf-8,'
    assert marker in page.text
    start = page.text.index(marker) + len(marker)
    csv_text = unquote(unescape(page.text[start : page.text.index('"', start)]))
    lines = csv_text.splitlines()
    # The code the planner writes down sits right next to the row it came from.
    assert lines[0].split(",")[:4] == ["Baris sumber", "Kode operasi", "ID operasi", "Kendaraan"]
    assert "Alokasi rekomendasi (L)" in lines[0]
    # One accepted row; the quarantined one is not in the file.
    assert len(lines) == 2
    assert re.match(r"CSV 2,\d{6}-\d{4},OPR-", lines[1])
    assert 'download="hasil-prediksi-rencana.csv"' in page.text
