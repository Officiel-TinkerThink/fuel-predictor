"""Optional real-browser checks. Run with Playwright and Chromium installed."""

import os
import shutil
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from fuel_predictor.delivery.rendering import STATIC_DIRECTORY, build_environment

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    root = tmp_path_factory.mktemp("ui-browser")
    shutil.copytree(STATIC_DIRECTORY, root / "statis")
    environment = build_environment()
    template = environment.from_string("""{% extends "base.html" %}
{% block content %}
{% for name in ['first', 'second'] %}
<section class="card"><h2>{{ name }}</h2><div class="table-wrap">
<table id="{{ name }}" data-list data-list-label="{{ name }}">
<thead><tr><th>Nama</th><th class="numeric">Liter</th><th>Waktu</th>
<th data-no-sort>Tindakan</th></tr></thead>
<tbody>{% for row in rows %}<tr>
<td>Unit {{ loop.index }}</td><td>{{ row.amount }}</td>
<td data-sort-value="{{ row.date }}">{{ row.date }}</td>
<td><a href="/masuk.html">Buka</a></td></tr>{% endfor %}</tbody></table></div></section>
{% endfor %}
<section class="card"><h2>Pending</h2>
<ul id="pending" class="row-list" data-list data-list-label="Pending"
 data-list-sort="amount:Alokasi:number">
{% for row in rows %}
<li data-sort-amount="{{ loop.index }}">Operasi {{ loop.index }}</li>{% endfor %}
</ul></section>
<section class="card"><table id="server" class="table--sortable"><thead><tr>
<th aria-sort="ascending"><a href="?urut=name">Nama</a></th></tr></thead>
<tbody><tr><td>Already paged</td></tr></tbody></table></section>
{% endblock %}""")
    amounts = ["2 L", "10 L", "1.234,5 L", "Belum cukup data"] + [f"{n} L" for n in range(4, 12)]
    rows = [
        {"amount": amount, "date": "2026-01-01" if n % 2 else "2025-12-31"}
        for n, amount in enumerate(amounts)
    ]
    (root / "index.html").write_text(
        template.render(
            page_title="Collections",
            page_lead=None,
            eyebrow=None,
            navigation=[
                SimpleNamespace(
                    title=None,
                    collapsible=False,
                    items=[SimpleNamespace(href="/", label="Ringkasan")],
                )
            ],
            active_path="/",
            caller_user=None,
            breadcrumbs=[],
            rows=rows,
        )
    )
    (root / "masuk.html").write_text(
        environment.get_template("masuk.html").render(
            username="",
            destination="/",
            csrf_token="test",
            notice=None,
            error=None,
        )
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=root)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as engine:
        executable = os.environ.get("FUEL_UI_BROWSER_EXECUTABLE", engine.chromium.executable_path)
        if not Path(executable).is_file():
            pytest.skip("Install Chromium with playwright install chromium")
        instance = engine.chromium.launch(executable_path=executable)
        yield instance
        instance.close()


@pytest.fixture
def page(browser, site):
    context = browser.new_context(viewport={"width": 1280, "height": 960})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(site)
    yield page
    context.close()
    assert not errors


def test_sort_page_search_and_independent_collections(page):
    visible = page.locator("#first tbody tr:visible")
    assert visible.count() == 5
    pager = page.get_by_role("navigation", name="Halaman first", exact=True)
    pager.get_by_role("button", name="Berikutnya").click()
    assert visible.first.locator("td").first.text_content() == "Unit 6"
    assert (
        page.locator("#second tbody tr:visible").first.locator("td").first.text_content()
        == "Unit 1"
    )
    page.locator("#first-search").fill("Unit 12")
    assert visible.count() == 1
    assert "Halaman 1 dari 1" in pager.text_content()
    assert pager.get_by_role("button", name="Berikutnya").is_disabled()
    page.locator("#first-search").fill("does-not-exist")
    assert visible.count() == 0
    assert "Menampilkan 0–0 dari 0" in pager.text_content()
    page.locator("#first-search").fill("")
    page.locator("#first-size").select_option("20")
    assert visible.count() == 12
    sort = page.locator("#first").get_by_role("button", name="Urutkan Liter")
    sort.focus()
    page.keyboard.press("Enter")
    assert visible.first.locator("td").nth(1).text_content() == "1.234,5 L"
    assert visible.last.locator("td").nth(1).text_content() == "Belum cukup data"
    page.keyboard.press("Enter")
    assert visible.first.locator("td").nth(1).text_content() == "2 L"
    assert visible.last.locator("td").nth(1).text_content() == "Belum cukup data"
    assert page.locator('#first th[aria-sort="ascending"]').count() == 1
    page.locator("#first").get_by_role("button", name="Urutkan Waktu").click()
    assert visible.first.locator("td").nth(2).text_content() == "2025-12-31"
    assert page.locator("#server button").count() == 0
    assert page.locator("#first th").last.locator("button").count() == 0


def test_row_lists_have_sorting_and_pagination(page):
    assert page.locator("#pending li:visible").count() == 5
    page.locator("#pending-sort").select_option("amount:desc")
    assert page.locator("#pending li:visible").first.text_content() == "Operasi 12"
    page.get_by_role("navigation", name="Halaman Pending").get_by_role(
        "button", name="Berikutnya"
    ).click()
    assert page.locator("#pending li:visible").first.text_content() == "Operasi 7"


def test_theme_persists_across_pages_and_tracks_system(page, site, tmp_path):
    page.emulate_media(color_scheme="dark")
    playwright.expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.get_by_label("Tampilan").select_option("light")
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.goto(site + "/masuk.html")
    assert page.get_by_label("Tampilan").input_value() == "light"
    page.get_by_label("Tampilan").select_option("dark")
    page.goto(site)
    assert page.locator("html").get_attribute("data-theme") == "dark"
    page.screenshot(path=str(tmp_path / "dark-desktop.png"), full_page=True)
    page.get_by_label("Tampilan").select_option("system")
    page.emulate_media(color_scheme="light")
    playwright.expect(page.locator("html")).to_have_attribute("data-theme", "light")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_phone_layout_keeps_hidden_rows_hidden(page, theme, tmp_path):
    page.set_viewport_size({"width": 320, "height": 844})
    page.get_by_role("button", name="Menu", exact=True).click()
    page.get_by_label("Tampilan").select_option(theme)
    page.get_by_role("button", name="Menu", exact=True).click()
    assert page.locator("#first tbody tr:visible").count() == 5
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("#first th").first.is_visible()
    page.screenshot(path=str(tmp_path / (theme + "-phone.png")), full_page=True)


def test_without_javascript_all_rows_and_actions_remain_available(browser, site):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(site)
    assert page.locator("#first tbody tr:visible").count() == 12
    assert page.locator("#pending li:visible").count() == 12
    assert not page.get_by_label("Tampilan").is_visible()
    assert page.locator("#first").get_by_role("link", name="Buka").count() == 12
    context.close()


def test_theme_still_works_when_storage_is_blocked(browser, site):
    context = browser.new_context()
    context.add_init_script(
        "Object.defineProperty(window, 'localStorage', {get() {throw Error('blocked')}})"
    )
    page = context.new_page()
    page.goto(site)
    page.get_by_label("Tampilan").select_option("dark")
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("#first tbody tr:visible").count() == 5
    context.close()
