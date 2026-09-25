"""Jinja2 environment, navigation, and the page-context helper (ADR 0007).

Templates receive plain data assembled here. They never touch a repository, a
use case, or a domain object's behaviour.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from fuel_predictor.application.identity import ActiveCaller
from fuel_predictor.domain.identity import Capability, UserRole

TEMPLATE_DIRECTORY = Path(__file__).parent / "templates"
STATIC_DIRECTORY = Path(__file__).parent / "static"

_ROLE_LABELS = {
    UserRole.OPERATOR: "Operator",
    UserRole.ADMINISTRATOR: "Administrator",
}


@dataclass(frozen=True, slots=True)
class NavigationItem:
    label: str
    href: str
    capability: Capability


@dataclass(frozen=True, slots=True)
class NavigationGroup:
    title: str | None
    items: tuple[NavigationItem, ...]
    # Daily work stays in view; the groups a planner opens once a week fold
    # away so the sidebar is not fifteen equally weighted links.
    collapsible: bool = False


NAVIGATION: tuple[NavigationGroup, ...] = (
    NavigationGroup(
        title=None,
        items=(NavigationItem("Ringkasan", "/", Capability.MANAGE_OWN_ACCOUNT),),
    ),
    NavigationGroup(
        title="Operasi Harian",
        items=(
            NavigationItem("Buat Prediksi", "/prediksi", Capability.CREATE_PREDICTION),
            NavigationItem(
                "Prediksi Massal", "/prediksi-operasi-massal", Capability.IMPORT_OPERATIONS
            ),
            NavigationItem("Riwayat Prediksi", "/riwayat-prediksi", Capability.CREATE_PREDICTION),
            NavigationItem("Armada", "/armada", Capability.CREATE_PREDICTION),
        ),
    ),
    NavigationGroup(
        title="BBM Aktual",
        items=(
            NavigationItem("Catat Aktual", "/bahan-bakar-aktual", Capability.RECORD_ACTUAL_FUEL),
            NavigationItem(
                "Impor Massal", "/bahan-bakar-aktual-massal", Capability.RECORD_ACTUAL_FUEL
            ),
        ),
    ),
    NavigationGroup(
        title="Pemantauan",
        collapsible=True,
        items=(
            NavigationItem(
                "Kinerja Model", "/pemantauan/kinerja-model", Capability.VIEW_MONITORING
            ),
            NavigationItem(
                "Pergeseran Data", "/pemantauan/pergeseran-data", Capability.VIEW_MONITORING
            ),
            NavigationItem(
                "Kesehatan Sistem", "/pemantauan/kesehatan-sistem", Capability.VIEW_MONITORING
            ),
        ),
    ),
    NavigationGroup(
        title="Model",
        collapsible=True,
        items=(
            NavigationItem("Pengelolaan Model", "/pengelolaan-model", Capability.VIEW_MODELS),
            NavigationItem("Impor Data Historis", "/impor-data-historis", Capability.MANAGE_MODELS),
            NavigationItem("Unggah Kandidat", "/model/unggah", Capability.MANAGE_MODELS),
            NavigationItem("Riwayat Paket", "/model/riwayat", Capability.VIEW_MODELS),
        ),
    ),
    NavigationGroup(
        title="Pengaturan",
        collapsible=True,
        items=(
            NavigationItem("Agen Saya", "/agen-saya", Capability.MANAGE_OWN_AGENTS),
            NavigationItem("Integrasi Agen", "/integrasi-agen", Capability.MANAGE_USERS),
            NavigationItem("Pengguna", "/pengguna", Capability.MANAGE_USERS),
            NavigationItem("Catatan Audit", "/audit", Capability.VIEW_AUDIT),
        ),
    ),
)


def build_environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIRECTORY),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["angka"] = format_decimal
    environment.filters["aktivitas"] = activity_label
    environment.filters["waktu"] = format_datetime
    return environment


def navigation_for(caller: ActiveCaller | None) -> list[SimpleNamespace]:
    """Show only what this caller may actually open.

    Groups and items are ``SimpleNamespace``, not ``dict``: Jinja resolves
    ``group.items`` as attribute access first, and a plain dict's own
    ``items()`` method would shadow a same-named "items" key.
    """
    if caller is None:
        return []
    groups: list[SimpleNamespace] = []
    for group in NAVIGATION:
        entries = [
            SimpleNamespace(label=item.label, href=item.href)
            for item in group.items
            if caller.allows(item.capability)
        ]
        if entries:
            groups.append(
                SimpleNamespace(title=group.title, items=entries, collapsible=group.collapsible)
            )
    return groups


def group_title_for(path: str) -> str | None:
    """The sidebar group a page belongs to, so the page header can echo it."""
    for group in NAVIGATION:
        if group.title and any(item.href == path for item in group.items):
            return group.title
    return None


def render(
    template_name: str,
    *,
    caller: ActiveCaller | None,
    page_title: str,
    active_path: str = "",
    eyebrow: str | None = None,
    page_lead: str | None = None,
    breadcrumbs: Sequence[dict[str, str | None]] | None = None,
    **context: object,
) -> str:
    template = _ENVIRONMENT.get_template(template_name)
    # The eyebrow repeats the sidebar group the page sits in, so the header
    # and the highlighted menu entry say the same thing. Pages outside the
    # navigation keep whatever eyebrow they passed.
    eyebrow = group_title_for(active_path) or eyebrow
    return template.render(
        caller_user=caller.user if caller else None,
        role_label=_ROLE_LABELS[caller.user.role] if caller else None,
        csrf_token=caller.csrf_token if caller else "",
        navigation=navigation_for(caller),
        active_path=active_path,
        page_title=page_title,
        eyebrow=eyebrow,
        page_lead=page_lead,
        breadcrumbs=list(breadcrumbs or []),
        **context,
    )


def render_standalone(template_name: str, **context: object) -> str:
    """Render a page that has no application shell, such as sign-in."""
    return _ENVIRONMENT.get_template(template_name).render(**context)


def render_error_page(title: str, message: str) -> str:
    return render_standalone("kesalahan.html", page_title=title, message=message)


# What a planned operation does, as the planner reads it.
ACTIVITY_LABELS = {
    "transport": "Mobilisasi",
    # Kept for operations planned before the two-choice form; not offered now.
    "lifting": "Lifting (tanpa mobilisasi)",
    "transport_and_lifting": "Mobilisasi + lifting",
}


def activity_label(value: str) -> str:
    return ACTIVITY_LABELS.get(value, value)


def format_decimal(value: float | None, digits: int = 2) -> str:
    """Indonesian number formatting: '.' groups thousands, ',' is the decimal mark.

    Trailing zero fraction digits are trimmed (43.20 -> "43,2", 42.00 -> "42"),
    matching the trimming `:g` gave the original f-string pages.
    """
    if value is None:
        return "-"
    formatted = f"{value:,.{digits}f}"
    integer_part, _, fraction_part = formatted.partition(".")
    fraction_part = fraction_part.rstrip("0")
    grouped = integer_part.replace(",", ".")
    return f"{grouped},{fraction_part}" if fraction_part else grouped


def format_datetime(value: datetime | None, zone: tzinfo = UTC) -> str:
    """Day and minute in the site's time zone. A naive value is a stored UTC time."""
    if value is None:
        return "-"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(zone).strftime("%d/%m/%Y %H:%M")


def configure_site_timezone(zone: tzinfo) -> None:
    """Show every time on every page in the zone the operators work in.

    One zone per deployment, set once when the application is built; operation
    codes are formed in the same zone, so the time in a code and the time on
    the screen next to it always agree.
    """
    global _SITE_ZONE
    _SITE_ZONE = zone
    _ENVIRONMENT.filters["waktu"] = partial(format_datetime, zone=zone)


def site_time(value: datetime | None) -> str:
    """A time as every page shows it, for text produced outside a template
    (a downloaded sheet)."""
    return format_datetime(value, _SITE_ZONE)


_SITE_ZONE: tzinfo = UTC


_ENVIRONMENT = build_environment()
