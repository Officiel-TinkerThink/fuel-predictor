"""Optional real-browser checks. Run with Playwright and Chromium installed."""

import os
import shutil
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from fuel_predictor.delivery.listing import ListingQuery, SortOption, paginate
from fuel_predictor.delivery.rendering import STATIC_DIRECTORY, build_environment

playwright = pytest.importorskip("playwright.sync_api")

# Playwright is deliberately not a declared dependency: these checks are
# optional and skip themselves above when it is absent, so the type checker
# never sees the real `Browser` and `Page` either. The aliases keep the
# signatures self-describing without claiming precision mypy cannot back.
type Browser = Any
type Page = Any


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    root = tmp_path_factory.mktemp("ui-browser")
    shutil.copytree(STATIC_DIRECTORY, root / "statis")
    environment = build_environment()
    template = environment.from_string("""{% extends "base.html" %}
{% import "components.html" as ui %}
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
<section class="card" id="server-section">
{{ ui.listing_toolbar(server_listing) }}
<table id="server" class="table--sortable"><thead><tr>
<th aria-sort="ascending"><a href="?urut=name">Nama</a></th></tr></thead>
<tbody><tr><td>Already paged</td></tr></tbody></table>
{{ ui.pagination(server_listing) }}
</section>
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
            server_listing=paginate(
                rows,
                ListingQuery(
                    q="Unit", sort="name", direction="asc", page=2, extra={"status": "active"}
                ),
                search=lambda row: ["Unit"],
                sorts=[SortOption("name", "Nama", lambda row: row["amount"])],
                default_sort="name",
            ),
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
def browser() -> Iterator[Browser]:
    with playwright.sync_playwright() as engine:
        executable = os.environ.get("FUEL_UI_BROWSER_EXECUTABLE", engine.chromium.executable_path)
        if not Path(executable).is_file():
            pytest.skip("Install Chromium with playwright install chromium")
        instance = engine.chromium.launch(executable_path=executable)
        yield instance
        instance.close()


@pytest.fixture
def page(browser: Browser, site: str) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 960})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(site)
    yield page
    context.close()
    assert not errors


def test_sort_page_search_and_independent_collections(page: Page) -> None:
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


def test_row_lists_have_sorting_and_pagination(page: Page) -> None:
    assert page.locator("#pending li:visible").count() == 5
    page.locator("#pending-sort").select_option("amount:desc")
    assert page.locator("#pending li:visible").first.text_content() == "Operasi 12"
    page.get_by_role("navigation", name="Halaman Pending").get_by_role(
        "button", name="Berikutnya"
    ).click()
    assert page.locator("#pending li:visible").first.text_content() == "Operasi 7"


def test_theme_follows_the_system_until_the_toggle_is_clicked(
    page: Page, site: str, tmp_path: Path
) -> None:
    toggle = page.locator("[data-theme-toggle]")
    moon = page.locator(".theme-toggle__moon")
    sun = page.locator(".theme-toggle__sun")

    # Untouched, the toggle has no opinion and the system decides.
    page.emulate_media(color_scheme="dark")
    playwright.expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert sun.is_visible() and not moon.is_visible()
    page.emulate_media(color_scheme="light")
    playwright.expect(page.locator("html")).to_have_attribute("data-theme", "light")

    # One glyph at a time, and it names where the click leads.
    assert moon.is_visible() and not sun.is_visible()
    assert toggle.get_attribute("aria-label") == "Ganti ke mode gelap"
    toggle.click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert sun.is_visible() and not moon.is_visible()
    assert toggle.get_attribute("aria-label") == "Ganti ke mode terang"
    page.screenshot(path=str(tmp_path / "dark-desktop.png"), full_page=True)
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == "dark"

    # Signed out, the sign-in page pins itself to light and offers no switch -
    # without disturbing the preference waiting behind it.
    page.goto(site + "/masuk.html")
    assert page.locator("html").get_attribute("data-theme") == "light"
    assert page.locator("[data-theme-toggle]").count() == 0
    page.goto(site)
    assert page.locator("html").get_attribute("data-theme") == "dark"

    # And a chosen theme outranks a system that says otherwise.
    page.emulate_media(color_scheme="light")
    assert page.locator("html").get_attribute("data-theme") == "dark"
    page.locator("[data-theme-toggle]").click()
    assert page.locator("html").get_attribute("data-theme") == "light"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_phone_layout_keeps_hidden_rows_hidden(page: Page, theme: str, tmp_path: Path) -> None:
    page.set_viewport_size({"width": 320, "height": 844})
    # The switch sits in the top bar, so a phone reaches it without the menu.
    if page.locator("html").get_attribute("data-theme") != theme:
        page.locator("[data-theme-toggle]").click()
    assert page.locator("html").get_attribute("data-theme") == theme
    assert page.locator("#first tbody tr:visible").count() == 5
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("#first th").first.is_visible()
    page.screenshot(path=str(tmp_path / (theme + "-phone.png")), full_page=True)


def test_without_javascript_all_rows_and_actions_remain_available(
    browser: Browser, site: str
) -> None:
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(site)
    assert page.locator("#first tbody tr:visible").count() == 12
    assert page.locator("#pending li:visible").count() == 12
    assert not page.locator("[data-theme-toggle]").is_visible()
    assert page.locator("#first").get_by_role("link", name="Buka").count() == 12
    context.close()


def test_theme_still_works_when_storage_is_blocked(browser: Browser, site: str) -> None:
    context = browser.new_context()
    context.add_init_script(
        "Object.defineProperty(window, 'localStorage', {get() {throw Error('blocked')}})"
    )
    page = context.new_page()
    page.goto(site)
    page.locator("[data-theme-toggle]").click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("#first tbody tr:visible").count() == 5
    context.close()


def test_page_size_is_in_pager_and_updates_client_list_immediately(page: Page) -> None:
    pager = page.get_by_role("navigation", name="Halaman first", exact=True)
    assert page.locator(".collection-toolbar select#first-size").count() == 0
    pager.get_by_role("button", name="Berikutnya").click()
    pager.get_by_label("Item per halaman").select_option("10")
    assert page.locator("#first tbody tr:visible").count() == 10
    assert "Halaman 1 dari 2" in pager.text_content()
    assert page.locator("#second tbody tr:visible").count() == 5


def test_server_page_size_is_independent_of_unsubmitted_search(page: Page) -> None:
    section = page.locator("#server-section")
    assert section.locator('form[role="search"] select[name="per"]').count() == 0
    assert section.locator('form[role="search"] input[name="per"]').input_value() == "5"
    section.get_by_label("Cari", exact=True).fill("Unsubmitted search")
    with page.expect_navigation():
        section.get_by_role("navigation").get_by_label("Item per halaman").select_option("10")
    assert parse_qs(urlsplit(page.url).query) == {
        "cari": ["Unit"],
        "urut": ["name"],
        "arah": ["asc"],
        "status": ["active"],
        "per": ["10"],
    }


def test_server_page_size_keeps_a_no_javascript_fallback(browser: Browser, site: str) -> None:
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(site)
    pager = page.locator("#server-section").get_by_role("navigation")
    pager.get_by_label("Item per halaman").select_option("20")
    with page.expect_navigation():
        pager.get_by_role("button", name="Ubah jumlah").click()
    assert parse_qs(urlsplit(page.url).query)["per"] == ["20"]
    context.close()


@pytest.fixture(scope="module")
def shell(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Two pages of the signed-in shell, with a sidebar tall enough to scroll."""
    root = tmp_path_factory.mktemp("ui-shell")
    shutil.copytree(STATIC_DIRECTORY, root / "statis")
    environment = build_environment()
    template = environment.from_string(
        '{% extends "base.html" %}{% block content %}'
        '<section class="card"><h2>{{ page_title }}</h2></section>{% endblock %}'
    )

    def group(
        title: str | None, items: list[tuple[str, str]], collapsible: bool = False
    ) -> SimpleNamespace:
        return SimpleNamespace(
            title=title,
            collapsible=collapsible,
            items=[SimpleNamespace(href=href, label=label) for href, label in items],
        )

    navigation = [
        group(None, [("/index.html", "Ringkasan")]),
        group("Operasi harian", [("/a.html", "Buat Prediksi"), ("/b.html", "Prediksi Massal")]),
        group("BBM aktual", [("/c.html", "Catat Aktual"), ("/target.html", "Impor Massal")]),
        group("Pemantauan", [("/d.html", "Operasi dan Alert")], collapsible=True),
        group("Model", [("/e.html", "Katalog Model")], collapsible=True),
        group("Pengaturan", [("/f.html", "Pengguna")], collapsible=True),
    ]
    for name, title in [("index.html", "Ringkasan"), ("target.html", "Impor Massal")]:
        (root / name).write_text(
            template.render(
                page_title=title,
                page_lead=None,
                eyebrow=None,
                navigation=navigation,
                active_path="/" + name,
                caller_user=SimpleNamespace(full_name="Administrator"),
                role_label="Administrator",
                csrf_token="test",
                breadcrumbs=[],
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


NAV_SCROLL_TOP = "() => document.querySelector('[data-nav-scroll]').scrollTop"
SCROLL_NAV_TO_END = (
    "() => {const n = document.querySelector('[data-nav-scroll]'); n.scrollTop = n.scrollHeight;}"
)


@pytest.fixture
def shell_page(browser: Browser, shell: str) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1180, "height": 560})
    page = context.new_page()
    page.goto(shell + "/index.html")
    yield page
    context.close()


def test_sidebar_keeps_its_scroll_offset_across_a_menu_click(shell_page: Page) -> None:
    shell_page.evaluate(SCROLL_NAV_TO_END)
    shell_page.wait_for_timeout(200)
    scrolled = shell_page.evaluate(NAV_SCROLL_TOP)
    assert scrolled > 0, "the sidebar must overflow for this test to mean anything"

    shell_page.get_by_role("link", name="Impor Massal").click()
    shell_page.wait_for_load_state()
    # Restoring too early clamps the offset against a taller, not-yet-final
    # scroller, which lands the sidebar somewhere in the middle instead.
    assert shell_page.evaluate(NAV_SCROLL_TOP) == scrolled


def test_account_row_holds_the_bottom_while_the_menu_scrolls(shell_page: Page) -> None:
    account = shell_page.locator(".app__account")
    resting = account.bounding_box()
    shell_page.evaluate(SCROLL_NAV_TO_END)
    shell_page.wait_for_timeout(200)
    assert shell_page.evaluate(NAV_SCROLL_TOP) > 0
    assert account.is_visible()
    assert account.bounding_box() == resting
    sidebar = shell_page.locator(".app__nav").bounding_box()
    assert resting["y"] + resting["height"] <= sidebar["y"] + sidebar["height"]


def test_menu_items_sit_indented_under_their_section_heading(shell_page: Page) -> None:
    heading = shell_page.locator(".nav-group__title", has_text="Operasi harian").first
    item = shell_page.get_by_role("link", name="Buat Prediksi").first
    assert item.bounding_box()["x"] > heading.bounding_box()["x"]
    # Every item shares that step, including one in a group with no heading.
    headless = shell_page.get_by_role("link", name="Ringkasan").first
    assert headless.bounding_box()["x"] == item.bounding_box()["x"]


def test_a_password_can_be_revealed_and_hidden_again(browser: Browser, site: str) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.goto(site + "/masuk.html")
    field = page.locator("#field-password")
    reveal = page.locator("[data-password-reveal]")
    field.fill("rahasia-yang-panjang")

    assert field.get_attribute("type") == "password"
    reveal.click()
    # The same input throughout, so what was typed survives the switch.
    assert field.get_attribute("type") == "text"
    assert reveal.get_attribute("aria-pressed") == "true"
    assert field.input_value() == "rahasia-yang-panjang"
    reveal.click()
    assert field.get_attribute("type") == "password"
    assert reveal.get_attribute("aria-pressed") == "false"
    assert field.input_value() == "rahasia-yang-panjang"
    context.close()


def test_without_javascript_the_reveal_button_stays_out_of_the_way(
    browser: Browser, site: str
) -> None:
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(site + "/masuk.html")
    assert page.locator("#field-password").count() == 1
    assert not page.locator("[data-password-reveal]").is_visible()
    context.close()
