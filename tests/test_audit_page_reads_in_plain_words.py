"""The audit page names actions in words and shows what was recorded.

Rows read "sign_in_failed" and "mcp_tool:predict_fuel", and the details each
record carried - the reason a sign-in failed, the note an agent call left -
were never rendered at all. A manager reading the page saw codes and had to
guess. Each action now has a label, the actor's kind is shown, details are
listed under the row, and the outcome can be narrowed to failures.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def test_actions_are_labelled_and_details_shown(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    with TestClient(app) as client:
        sign_in = client.get("/masuk")
        client.post(
            "/masuk",
            data={"username": "admin", "password": "salah", "csrf_token": _csrf(sign_in.text)},
        )
        client.post(
            "/masuk",
            data={"username": _ADMIN[0], "password": _ADMIN[1], "csrf_token": _csrf(sign_in.text)},
        )
        page = client.get("/audit")
        by_code = client.get("/audit?cari=sign_in_failed")

    assert page.status_code == 200
    assert "Masuk gagal" in page.text
    # The successful sign-in that followed is not in the trail at all.
    assert "Masuk berhasil" not in page.text and "sign_in_succeeded" not in page.text
    # The raw code stays findable for anyone holding a log line: on hover,
    # and through the search - but it is not a second line on every row.
    assert 'title="sign_in_failed"' in page.text
    assert '<code class="mono-id">sign_in_failed</code>' not in page.text
    assert "Masuk gagal" in by_code.text
    # Only an outcome that needs a look is a badge.
    assert 'class="badge' in page.text.split('data-outcome="failed"', 1)[1].split("</tr>", 1)[0]
    # A filter on outcome, so failures can be read on their own.
    assert 'name="hasil"' in page.text
    assert 'data-outcome="failed"' in page.text


def test_every_detail_an_event_writes_has_a_word() -> None:
    """A trained candidate's row read "rows: 12" among Indonesian labels."""
    from datetime import UTC, datetime

    from fuel_predictor.delivery.audit_view import audit_row
    from fuel_predictor.domain.identity import AuditOutcome, AuditRecord

    row = audit_row(
        AuditRecord(
            audit_id="AUD-1",
            occurred_at=datetime(2026, 9, 26, tzinfo=UTC),
            actor="admin",
            actor_kind="user",
            action="model_candidate_trained",
            outcome=AuditOutcome.SUCCEEDED,
            subject="MDL-1",
            details={
                "dataset": "DSV-000003",
                "rows": 12,
                "previous_version_id": "MDL-0",
                "redirect_uris": "https://agen.example/kembali",
            },
        )
    )

    labels = [label for label, _value in row["details"]]  # type: ignore[attr-defined]
    assert labels == ["dataset", "baris data latih", "model sebelumnya", "alamat kembali"]
