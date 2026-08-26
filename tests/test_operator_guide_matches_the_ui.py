"""The operator guide must name things the operator can actually find.

A guide that tells someone to press a button that does not exist is worse than
no guide: it makes them doubt themselves rather than the document. Every one of
these mismatches was real — the guide said "Unggah Model" when the menu says
"Unggah Kandidat", and told the reader to press "Hitung Prediksi", which is not
a button anywhere in the application.

They survived because nothing connected the prose to the interface. These tests
do, so the guide fails the build when the UI is renamed under it rather than
quietly going stale.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from fuel_predictor.delivery.rendering import NAVIGATION

_GUIDE = Path(__file__).resolve().parents[1] / "docs" / "production" / "panduan-operator.md"
_IMAGES = _GUIDE.parent / "images"


@pytest.fixture(scope="module")
def guide() -> str:
    return _GUIDE.read_text(encoding="utf-8")


def _navigation_names() -> set[str]:
    names = {item.label for group in NAVIGATION for item in group.items}
    names |= {group.title for group in NAVIGATION if group.title}
    return names


def test_every_menu_the_guide_names_exists_in_the_navigation(guide: str) -> None:
    referenced = set(re.findall(r"[Mm]enu \*\*([^*]+)\*\*", guide))
    assert referenced, "the guide should name menus; the pattern may have changed"

    unknown = sorted(referenced - _navigation_names())

    assert unknown == [], f"guide names menus that do not exist: {unknown}"


def test_every_screenshot_the_guide_references_exists(guide: str) -> None:
    referenced = re.findall(r"\]\((images/[^)]+)\)", guide)
    assert referenced, "the guide should embed screenshots"

    missing = sorted(name for name in referenced if not (_GUIDE.parent / name).is_file())

    assert missing == [], f"guide references missing images: {missing}"


def test_no_screenshot_placeholders_remain(guide: str) -> None:
    """Placeholders block the usability test — a tester cannot use a guide with holes."""
    assert "Sisipkan tangkapan layar" not in guide


def test_every_screenshot_has_alt_text(guide: str) -> None:
    """Alt text is what a screen-reader user gets instead of the picture."""
    without_alt = re.findall(r"!\[\s*\]\((images/[^)]+)\)", guide)

    assert without_alt == [], f"screenshots with empty alt text: {without_alt}"


def test_no_stored_image_is_unused() -> None:
    """An orphaned screenshot is one nobody will remember to re-capture."""
    stored = {path.name for path in _IMAGES.glob("*.png")}
    guide = _GUIDE.read_text(encoding="utf-8")
    used = {Path(name).name for name in re.findall(r"\]\((images/[^)]+)\)", guide)}

    assert stored - used == set(), f"unused screenshots: {sorted(stored - used)}"


def test_the_guide_leads_with_the_estimate_versus_actual_distinction(guide: str) -> None:
    """The one misunderstanding that makes an operator mis-plan.

    Task 3 of the usability test checks the reader can state this, so the guide
    has to say it before anything else, not bury it.
    """
    opening = guide[: guide.index("## Daftar isi")]

    assert "bahan bakar yang perlu disiapkan" in opening
    assert "bukan catatan bahan bakar yang benar-benar terpakai" in opening


def test_the_standalone_html_is_not_stale() -> None:
    """The HTML copy must match the markdown it was built from.

    A generated copy that drifts is worse than none: the participant reading it
    has no way to tell it is out of date. Rebuilding is one command, so there is
    no excuse for the committed file lagging behind.
    """
    build = _GUIDE.parent / "build-operator-guide-html.py"
    html = _GUIDE.parent / "panduan-operator.html"
    assert build.is_file() and html.is_file()

    before = html.read_bytes()
    subprocess.run(
        [sys.executable, str(build)], check=True, capture_output=True, cwd=str(_GUIDE.parent)
    )
    after = html.read_bytes()

    assert after == before, (
        "docs/production/panduan-operator.html is out of date; "
        "run python docs/production/build-operator-guide-html.py and commit the result"
    )


def test_the_standalone_html_references_nothing_external() -> None:
    """It has to open with no network and no sibling files."""
    html = (_GUIDE.parent / "panduan-operator.html").read_text(encoding="utf-8")

    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "<script" not in html
    assert 'src="images/' not in html
    assert html.count("data:image/png;base64,") == len(list(_IMAGES.glob("*.png")))
