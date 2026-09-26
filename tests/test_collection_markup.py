"""Every record table opts into one list controller; comparison matrices stay whole."""

import re

from fuel_predictor.delivery.rendering import TEMPLATE_DIRECTORY, build_environment


def test_record_tables_declare_how_they_are_paged_and_sorted() -> None:
    for path in TEMPLATE_DIRECTORY.glob("*.html"):
        for table in re.findall(r"<table\b[^>]*>", path.read_text()):
            strategies = (
                "data-list" in table,
                "table--sortable" in table,
                "data-static-table" in table,
            )
            assert sum(strategies) == 1, f"{path.name}: missing or conflicting list controls"


def test_every_document_loads_theme_before_styles_and_offers_a_switch() -> None:
    # One <head> for every document (_head.html): the theme script runs before
    # the stylesheet paints, so a dark-mode reader never sees a white flash.
    head = (TEMPLATE_DIRECTORY / "_head.html").read_text()
    assert head.index("/statis/theme.js") < head.index("/statis/app.css")
    for path in TEMPLATE_DIRECTORY.glob("*.html"):
        source = path.read_text()
        if "<!DOCTYPE html>" not in source:
            continue
        assert "heads.head(" in source, path.name
        # A page either offers the switch or pins its own appearance, never
        # both and never neither.
        offers = '{% include "theme-toggle.html" %}' in source
        pinned = "data-theme-locked" in source
        assert offers != pinned, path.name


def test_all_templates_compile() -> None:
    environment = build_environment()
    for name in environment.list_templates():
        environment.get_template(name)
