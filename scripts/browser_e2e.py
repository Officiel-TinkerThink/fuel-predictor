"""End-to-end browser scenarios, each recorded as an MP4.

    python scripts/browser_e2e.py http://127.0.0.1:8300 operator kata-sandi-demo-1 .e2e/videos

These exist because `app.js` is 163 lines that the Python suite never executes:
it asserts against the HTML the server rendered, so the lifting-hours toggle,
the stop-sequence add/reorder/remove controls, and the file-input hint could all
break without a single test noticing. The first person to find out would be an
operator.

Every scenario asserts. The video is a by-product that lets someone watch the
same run and disagree with it — not the deliverable on its own.
"""

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_harness import Browser, record  # noqa: E402

Scenario = Callable[[Browser], Awaitable[None]]

_HISTORY = (
    "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),Sumber Jarak\n"
    "ANGBER,transport,,32,manual\n"
    "ANGBER,transport_and_lifting,2,45,manual\n"
    "ANGBER,lifting,,20,manual\n"
    "ANGBER,transport,,dua puluh,manual\n"
    "ANGBER,transport,,-5,manual\n"
)


class Check:
    """Collects assertion outcomes so one failure does not hide the rest."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def that(self, label: str, condition: bool, detail: str = "") -> None:
        mark = "OK  " if condition else "FAIL"
        print(f"    {mark}  {label}" + (f"  [{detail}]" if detail else ""))
        if not condition:
            self.failures.append(label)


CHECK = Check()


async def _sign_in(page: Browser, base: str, user: str, password: str) -> None:
    await page.navigate(f"{base}/masuk")
    await page.fill("input[name=username]", user)
    await page.fill("input[name=password]", password)
    await page.click("form[action='/masuk'] button[type=submit]", settle=2.0)


def sign_in_scenario(base: str, user: str, password: str) -> Scenario:
    async def scenario(page: Browser) -> None:
        await page.navigate(f"{base}/masuk")
        await page.pause(1.0)
        CHECK.that("sign-in form is shown", "Masuk" in await page.text())
        await page.fill("input[name=username]", user)
        await page.fill("input[name=password]", password)
        await page.pause(0.6)
        await page.click("form[action='/masuk'] button[type=submit]", settle=2.2)
        body = await page.text()
        CHECK.that("signed in and the overview loads", "Ringkasan" in body)
        CHECK.that("the sidebar is present", "Buat Prediksi" in body)
        await page.pause(1.2)

    return scenario


def prediction_scenario(base: str, user: str, password: str) -> Scenario:
    """The JavaScript the Python suite cannot reach."""

    async def scenario(page: Browser) -> None:
        await _sign_in(page, base, user, password)
        await page.navigate(f"{base}/prediksi")
        await page.pause(1.0)

        # syncLifting: the field hides for transport, appears for lifting modes.
        await page.fill("#field-activity_mode", "transport")
        hidden = not await page.visible("#lifting-field")
        CHECK.that("lifting hours hidden for transport", hidden)
        await page.pause(0.7)

        await page.fill("#field-activity_mode", "transport_and_lifting")
        shown = await page.visible("#lifting-field")
        CHECK.that("lifting hours shown for transport_and_lifting", shown)
        required = await page.evaluate(
            "document.querySelector('#field-lifting_hours').required", settle=0.05
        )
        CHECK.that("lifting hours becomes required", bool(required))
        await page.pause(0.7)

        # Stop sequence: add, fill, reorder, remove.
        before = await page.count("#stop-sequence .stop-row")
        await page.click("#add-stop", settle=0.7)
        after = await page.count("#stop-sequence .stop-row")
        CHECK.that("add-stop appends a row", after == before + 1, f"{before} -> {after}")

        rows = await page.count("#stop-sequence .stop-row")
        for index in range(rows):
            await page.fill(
                f"#stop-sequence .stop-row:nth-child({index + 1}) input[name=stop_sequence]",
                f"Titik {index + 1}",
                settle=0.25,
            )
        await page.pause(0.8)
        expected = [f"Titik {n + 1}" for n in range(rows)]
        CHECK.that(
            "stops carry the values typed",
            await page.values("input[name=stop_sequence]") == expected,
        )

        # Move the last row up; its value must travel with it.
        await page.click(
            f"#stop-sequence .stop-row:nth-child({rows}) button[data-action='up']", settle=0.8
        )
        moved = await page.values("input[name=stop_sequence]")
        CHECK.that(
            "moving a stop up reorders its value",
            moved[rows - 2] == f"Titik {rows}",
            " | ".join(moved),
        )
        await page.pause(0.8)

        await page.click(
            "#stop-sequence .stop-row:nth-child(1) button[data-action='remove']", settle=0.8
        )
        remaining = await page.count("#stop-sequence .stop-row")
        CHECK.that("remove deletes exactly one row", remaining == rows - 1, f"{remaining}")
        await page.pause(0.8)

        await page.fill("#field-total_distance_km", "35")
        await page.fill("#field-lifting_hours", "2")
        await page.pause(0.6)
        await page.click("form[action='/operasi-harian'] button[type=submit]", settle=2.2)
        saved = await page.text()
        CHECK.that("the operation is saved", "Operasi harian tersimpan" in saved)
        await page.pause(0.8)

        # Target the estimate form specifically: a bare "button" selector picks
        # the first in the DOM, which is the sidebar's sign-out.
        await page.click("form[action$='/prediksi'] button[type=submit]", settle=2.6)
        result = await page.text()
        CHECK.that("an estimate is produced", "Estimasi kebutuhan" in result)
        CHECK.that(
            "the estimate is framed as prepared fuel, not consumption",
            "bukan konsumsi" in result,
        )
        await page.pause(1.5)

    return scenario


def bulk_scenario(base: str, user: str, password: str) -> Scenario:
    async def scenario(page: Browser) -> None:
        await _sign_in(page, base, user, password)
        await page.navigate(f"{base}/prediksi-operasi-massal")
        await page.pause(1.0)
        await page.evaluate(
            "(() => { const f = document.querySelector("
            + json.dumps("form[action='/prediksi-operasi-massal']")
            + "); const i = f.querySelector('input[type=file]');"
            " const dt = new DataTransfer();"
            " dt.items.add(new File([" + json.dumps(_HISTORY) + "],"
            " 'rencana-agustus.csv', {type: 'text/csv'}));"
            " i.files = dt.files;"
            " i.dispatchEvent(new Event('change', {bubbles: true})); })()",
            settle=1.0,
        )
        # app.js replaces the file hint with the chosen filename.
        CHECK.that(
            "the chosen filename is shown to the operator",
            "rencana-agustus.csv" in await page.text(),
        )
        await page.pause(1.0)
        await page.click("form[action='/prediksi-operasi-massal'] button[type=submit]", settle=3.0)
        body = await page.text()
        CHECK.that("valid rows are predicted", "berhasil diprediksi" in body.lower())
        CHECK.that("invalid rows are quarantined with reasons", "dikarantina" in body.lower())
        CHECK.that("a reason names the lifting-hours rule", "Jam lifting" in body)
        await page.pause(2.0)

    return scenario


def monitoring_scenario(base: str, user: str, password: str) -> Scenario:
    async def scenario(page: Browser) -> None:
        await _sign_in(page, base, user, password)
        for path, expected in (
            ("/pemantauan/kinerja-model", "Kinerja Model"),
            ("/pemantauan/pergeseran-data", "Pergeseran"),
            ("/pemantauan/kesehatan-sistem", "Kesehatan Sistem"),
        ):
            await page.navigate(f"{base}{path}")
            CHECK.that(f"{path} renders", expected in await page.text())
            await page.pause(1.6)

    return scenario


def governance_scenario(base: str, user: str, password: str) -> Scenario:
    async def scenario(page: Browser) -> None:
        await _sign_in(page, base, user, password)
        await page.navigate(f"{base}/pengelolaan-model")
        await page.pause(1.2)
        body = await page.text()
        CHECK.that("the active model is shown", "Model aktif" in body)
        CHECK.that("promotion is described as manual", "Promosikan manual" in body)
        candidates = await page.count("form[action*='/promosikan']")
        CHECK.that("a candidate awaits review", candidates >= 1, f"{candidates}")
        await page.pause(1.2)
        if candidates:
            await page.click("form[action*='/promosikan'] button[type=submit]", settle=3.0)
            CHECK.that("promotion completes", "dipromosikan" in (await page.text()).lower())
            await page.pause(1.6)

    return scenario


def agent_scenario(base: str, user: str, password: str) -> Scenario:
    async def scenario(page: Browser) -> None:
        await _sign_in(page, base, user, password)
        await page.navigate(f"{base}/integrasi-agen")
        await page.pause(1.2)
        CHECK.that(
            "the privileged scope is not pre-ticked",
            not await page.evaluate(
                "document.querySelector(\"input[value='models:admin']\").checked", settle=0.05
            ),
        )
        await page.fill("#field-name", "Agen Demo")
        await page.pause(0.8)
        await page.click("form[action='/integrasi-agen'] button[type=submit]", settle=2.4)
        issued = await page.text()
        CHECK.that("a credential is issued", "fpa_" in issued)
        CHECK.that("it is shown once and cannot be recovered", "satu kali" in issued)
        await page.pause(2.0)

        await page.click("form[action*='/cabut'] button[type=submit]", settle=2.2)
        CHECK.that("the client is revoked", "Dicabut" in await page.text())
        await page.pause(1.5)

    return scenario


async def main() -> int:
    base, user, password, out = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
    scenarios: list[tuple[str, Scenario]] = [
        ("01-masuk", sign_in_scenario(base, user, password)),
        ("02-prediksi-dan-rute", prediction_scenario(base, user, password)),
        ("03-prediksi-massal", bulk_scenario(base, user, password)),
        ("04-pemantauan", monitoring_scenario(base, user, password)),
        ("05-pengelolaan-model", governance_scenario(base, user, password)),
        ("06-integrasi-agen", agent_scenario(base, user, password)),
    ]
    port = 9340
    for name, scenario in scenarios:
        print(f"\n  {name}")
        await record(scenario, out / f"{name}.mp4", port=port)
        port += 1

    print(f"\n{'PASS' if not CHECK.failures else f'{len(CHECK.failures)} CHECK(S) FAILED'}")
    for failure in CHECK.failures:
        print(f"  failed: {failure}")
    return 1 if CHECK.failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
