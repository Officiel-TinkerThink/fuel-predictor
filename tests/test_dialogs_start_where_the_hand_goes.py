"""A confirmation dialog opens with focus on something visible and safe.

Every dialog began with a visually hidden "Tutup" button, so opening one by
keyboard put focus on nothing anyone could see, and Enter closed it again.
Now focus lands on the dialog's field when it asks for one, and otherwise on
"Kembali" - never on the destructive button, where Enter would confirm.
"""

from fuel_predictor.delivery.rendering import TEMPLATE_DIRECTORY, build_environment


def _confirm(reason_field: bool) -> str:
    template = build_environment().from_string(
        '{% import "components.html" as ui %}'
        "{{ ui.confirm_button('hapus', 'Hapus', 'Hapus?', 'Tidak bisa diurungkan.', "
        "'/hapus', 'token', reason_field=" + ("true" if reason_field else "false") + ") }}"
    )
    rendered: str = template.render()
    return rendered


def test_without_a_field_focus_starts_on_the_way_out() -> None:
    dialog = _confirm(reason_field=False)

    assert 'data-dialog-close="hapus" autofocus>Kembali' in dialog
    assert dialog.count("autofocus") == 1


def test_with_a_field_focus_starts_in_it() -> None:
    dialog = _confirm(reason_field=True)

    # The first control in the dialog is the reason; nothing claims focus first.
    assert "autofocus" not in dialog
    assert dialog.index('name="reason"') < dialog.index('type="submit"')


def test_no_dialog_starts_with_a_hidden_control() -> None:
    for path in TEMPLATE_DIRECTORY.glob("*.html"):
        assert 'class="visually-hidden" value="batal"' not in path.read_text(), path.name
