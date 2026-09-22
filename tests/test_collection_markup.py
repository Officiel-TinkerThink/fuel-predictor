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


def test_every_document_loads_theme_before_styles_and_offers_a_picker() -> None:
    for path in TEMPLATE_DIRECTORY.glob("*.html"):
        source = path.read_text()
        if "<!DOCTYPE html>" not in source:
            continue
        assert source.index("/statis/theme.js") < source.index("/statis/app.css"), path.name
        assert '{% include "theme-picker.html" %}' in source, path.name


def test_all_templates_compile() -> None:
    environment = build_environment()
    for name in environment.list_templates():
        environment.get_template(name)
