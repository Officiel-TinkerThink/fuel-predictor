"""Jinja2 environment, navigation, and the page-context helper (ADR 0007).

Templates receive plain data assembled here. They never touch a repository, a
use case, or a domain object's behaviour.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from fuel_predictor.application.identity import ActiveCaller
from fuel_predictor.domain.identity import Capability, UserRole

TEMPLATE_DIRECTORY = Path(__file__).parent / "templates"
STATIC_DIRECTORY = Path(__file__).parent / "static"

_ROLE_LABELS = {
    UserRole.OPERATOR: "Operator",
    UserRole.MANAGER: "Manajer",
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


NAVIGATION: tuple[NavigationGroup, ...] = (
    NavigationGroup(
        title=None,
        items=(NavigationItem("Ringkasan", "/", Capability.VIEW_MONITORING),),
    ),
    NavigationGroup(
        title="Operasi Harian",
        items=(
            NavigationItem("Buat Prediksi", "/prediksi", Capability.CREATE_PREDICTION),
            NavigationItem(
                "Prediksi Massal", "/prediksi-operasi-massal", Capability.IMPORT_OPERATIONS
            ),
            # "Riwayat Prediksi" is in the plan's nav but has no page yet; add it
            # here once it exists rather than linking a 404.
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
        items=(
            # The plan calls for three separate views (Kinerja Model / Pergeseran
            # Data / Kesehatan Sistem); only one combined page exists so far.
            NavigationItem(
                "Kinerja Prediksi", "/kinerja-prediksi", Capability.VIEW_MONITORING
            ),
            NavigationItem(
                "Pemantauan Operasi", "/pemantauan-operasi", Capability.VIEW_MONITORING
            ),
        ),
    ),
    NavigationGroup(
        title="Model",
        items=(
            # "Unggah Kandidat" (external ingestion, ADR 0009) and "Riwayat dan
            # Rollback" (ADR 0010) are Phase 2 work; not linked until they exist.
            NavigationItem("Pengelolaan Model", "/pengelolaan-model", Capability.VIEW_MODELS),
        ),
    ),
    NavigationGroup(
        title="Pengaturan",
        items=(
            # "Integrasi Agen" is Phase 4 (MCP); not linked until it exists.
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
            groups.append(SimpleNamespace(title=group.title, items=entries))
    return groups


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


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%d/%m/%Y %H:%M")


_ENVIRONMENT = build_environment()
