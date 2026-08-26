"""Accessibility invariants for every page an operator can reach.

The design system was built to the plan's checklist, but nothing verified it,
so a regression would have been invisible until someone using a screen reader
or a keyboard hit it. These parse the real rendered HTML rather than driving a
browser: the checks below are structural, so they need no Chrome, run in a
second, and cannot flake.

They are not a substitute for testing with an actual assistive technology.
What they do is stop the cheap, common regressions — an input that lost its
label, an icon button with no name, a second <h1> — from shipping unnoticed.
"""

from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.delivery.rendering import NAVIGATION
from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")
_PATHS = [item.href for group in NAVIGATION for item in group.items]


class _Page(HTMLParser):
    """Collects only what the assertions below need."""

    def __init__(self) -> None:
        super().__init__()
        self.lang: str | None = None
        self.headings: list[str] = []
        self.controls: list[dict[str, str]] = []
        self.labels_for: set[str] = set()
        self.images: list[dict[str, str]] = []
        self.ids: set[str] = set()
        self.buttons: list[dict[str, str]] = []
        self._open_button: dict[str, str] | None = None
        self._open_heading: str | None = None
        self._label_depth = 0
        self.wrapped: list[int] = []
        self.skip_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        if identifier := attributes.get("id"):
            self.ids.add(identifier)
        if tag == "html":
            self.lang = attributes.get("lang")
        elif tag in {"h1", "h2", "h3"}:
            self._open_heading = tag
        elif tag == "label":
            # A control wrapped in <label> is labelled implicitly, which is
            # valid and common for checkboxes. Missing that reports correct
            # markup as broken.
            self._label_depth += 1
            if target := attributes.get("for"):
                self.labels_for.add(target)
        elif tag in {"input", "select", "textarea"}:
            if attributes.get("type") not in {"hidden", "submit", "button"}:
                if self._label_depth:
                    self.wrapped.append(len(self.controls))
                self.controls.append(attributes)
        elif tag == "img":
            self.images.append(attributes)
        elif tag == "button":
            self._open_button = {**attributes, "text": ""}
        elif tag == "a" and "skip-link" in attributes.get("class", ""):
            self.skip_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self._label_depth = max(0, self._label_depth - 1)
        if tag == "button" and self._open_button is not None:
            self.buttons.append(self._open_button)
            self._open_button = None
        elif tag == self._open_heading:
            self._open_heading = None

    def handle_data(self, data: str) -> None:
        if self._open_button is not None:
            self._open_button["text"] += data
        elif self._open_heading == "h1":
            self.headings.append(data.strip())


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, _Page]:
    directory: Path = tmp_path_factory.mktemp("a11y")
    app = create_app(
        database_path=directory / "operations.sqlite3", bootstrap_administrator=_ADMIN
    )
    rendered: dict[str, _Page] = {}
    with TestClient(app) as client:
        sign_in = client.get("/masuk")
        marker = 'name="csrf_token" value="'
        start = sign_in.text.index(marker) + len(marker)
        rendered["/masuk"] = _parse(sign_in.text)
        client.post(
            "/masuk",
            data={
                "username": _ADMIN[0],
                "password": _ADMIN[1],
                "csrf_token": sign_in.text[start : sign_in.text.index('"', start)],
            },
            follow_redirects=False,
        )
        for path in _PATHS:
            response = client.get(path)
            assert response.status_code == 200, f"{path} -> {response.status_code}"
            rendered[path] = _parse(response.text)
    return rendered


def _parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


def _named(index: int, control: dict[str, str], page: _Page) -> bool:
    """Named by a wrapping <label>, a <label for>, aria-label, or aria-labelledby."""
    if index in page.wrapped:
        return True
    if control.get("aria-label", "").strip():
        return True
    if control.get("aria-labelledby", "").strip():
        return True
    return control.get("id", "") in page.labels_for


def test_every_page_declares_its_language(pages: dict[str, _Page]) -> None:
    """Screen readers pick a pronunciation from this. The application is Indonesian."""
    for path, page in pages.items():
        assert page.lang == "id", f"{path} declares lang={page.lang!r}"


def test_every_page_has_exactly_one_top_level_heading(pages: dict[str, _Page]) -> None:
    """Two <h1>s or none both break heading-based navigation."""
    for path, page in pages.items():
        assert len(page.headings) == 1, f"{path} has {len(page.headings)} <h1>: {page.headings}"


def test_every_form_control_has_an_accessible_name(pages: dict[str, _Page]) -> None:
    """An unlabelled input is announced as just "edit text"."""
    unnamed = {
        path: [
            control.get("name") or control.get("id") or "(anonymous)"
            for index, control in enumerate(page.controls)
            if not _named(index, control, page)
        ]
        for path, page in pages.items()
    }
    offenders = {path: names for path, names in unnamed.items() if names}

    assert offenders == {}, f"form controls with no accessible name: {offenders}"


def _reads_as_words(text: str) -> bool:
    """Whether the content would announce as something meaningful.

    A glyph is not a name. "↑" announces as "up arrow", which says nothing
    about *what* moves up — so a button whose only content is symbols still
    needs an aria-label.
    """
    return any(character.isalnum() for character in text)


def test_every_button_has_a_discernible_name(pages: dict[str, _Page]) -> None:
    """Icon-only buttons need aria-label; a bare glyph announces as nothing useful."""
    offenders = {}
    for path, page in pages.items():
        anonymous = [
            button.get("data-action") or button.get("class") or button["text"].strip() or "(empty)"
            for button in page.buttons
            if not _reads_as_words(button["text"])
            and not button.get("aria-label", "").strip()
        ]
        if anonymous:
            offenders[path] = anonymous

    assert offenders == {}, f"buttons with no name: {offenders}"


def test_every_image_has_alt_text(pages: dict[str, _Page]) -> None:
    """Decorative images still need alt="" so they are skipped rather than read."""
    offenders = {
        path: [image for image in page.images if "alt" not in image]
        for path, page in pages.items()
    }
    offenders = {path: images for path, images in offenders.items() if images}

    assert offenders == {}, f"images without an alt attribute: {offenders}"


def test_every_signed_in_page_offers_a_skip_link(pages: dict[str, _Page]) -> None:
    """Without it a keyboard user tabs the whole sidebar on every page."""
    missing = [path for path, page in pages.items() if path != "/masuk" and not page.skip_link]

    assert missing == [], f"pages with no skip link: {missing}"


def test_aria_labelledby_points_at_something_real(pages: dict[str, _Page]) -> None:
    """A dangling reference is worse than none: it names the control nothing."""
    offenders = {}
    for path, page in pages.items():
        dangling = [
            reference
            for control in page.controls
            for reference in control.get("aria-labelledby", "").split()
            if reference not in page.ids
        ]
        if dangling:
            offenders[path] = dangling

    assert offenders == {}, f"aria-labelledby pointing at missing ids: {offenders}"
