"""The sheet for planning many operations at once.

It asks what the single form asks, in the form's words: the unit, the
activity, the distance, the lifting hours, the stops. The category (every
unit is ANGBER) and the distance source (a typed distance is a manual one)
are not asked; sheets that still carry those columns are read as before.
With the fleet passed in, the unit and activity columns are dropdowns, so a
name cannot be misspelled.
"""

import csv
from collections.abc import Sequence
from io import BytesIO, StringIO
from typing import cast

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

BULK_PREDICTION_TEMPLATE_HEADERS = (
    "Kendaraan",
    "Aktivitas (wajib)",
    "Jarak Total (km) (wajib)",
    "Jam Lifting (opsional)",
    "Urutan Pemberhentian (opsional)",
)
ACTIVITY_CHOICES = ("Mobilisasi", "Mobilisasi + lifting")
# Rows the dropdowns cover; far more than a day's plan.
_ROWS = 500


def csv_template() -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(BULK_PREDICTION_TEMPLATE_HEADERS)
    return output.getvalue().encode("utf-8-sig")


def xlsx_template(vehicles: Sequence[tuple[str, bool]] = ()) -> bytes:
    """`vehicles` is the fleet as (name, can lift), in the catalog's order."""
    workbook = Workbook()
    worksheet = cast(Worksheet, workbook.active)
    worksheet.title = "Operasi Harian"
    worksheet.append(BULK_PREDICTION_TEMPLATE_HEADERS)
    _style_header(worksheet)
    for column, width in zip("ABCDE", (26, 24, 24, 22, 48), strict=True):
        worksheet.column_dimensions[column].width = width
    worksheet.freeze_panes = "A2"

    activity = DataValidation(
        type="list", formula1='"' + ",".join(ACTIVITY_CHOICES) + '"', allow_blank=True
    )
    activity.error = 'Pilih "Mobilisasi" atau "Mobilisasi + lifting".'
    worksheet.add_data_validation(activity)
    activity.add(f"B2:B{_ROWS}")

    if vehicles:
        # The names live on a hidden sheet: a dropdown written inline is cut
        # off at 255 characters, which the fleet already exceeds. Its header
        # matches no column of the plan, so the import does not read it.
        names = workbook.create_sheet("Daftar unit")
        names.append(("Nama unit (daftar pilihan)",))
        for name, _can_lift in vehicles:
            names.append((name,))
        names.sheet_state = "hidden"
        unit = DataValidation(
            type="list", formula1=f"='Daftar unit'!$A$2:$A${len(vehicles) + 1}", allow_blank=True
        )
        unit.error = "Pilih unit dari daftar; namanya sama dengan di menu Armada."
        worksheet.add_data_validation(unit)
        unit.add(f"A2:A{_ROWS}")

    lifting = [name for name, can_lift in vehicles if can_lift]
    instructions = workbook.create_sheet("Petunjuk", 1)
    instructions["A1"] = "Cara mengisi: satu baris per operasi"
    instructions["A1"].font = Font(bold=True, color="FFFFFF")
    instructions["A1"].fill = PatternFill("solid", fgColor="185C43")
    instructions.append(("Kolom", "Status", "Petunjuk"))
    for cell in instructions[2]:
        cell.font = Font(bold=True)
    instructions.append(
        (
            "Kendaraan",
            "Disarankan",
            "Pilih unit dari daftar; namanya sama dengan di menu Armada. Tanpa kendaraan, "
            "estimasi memakai rata-rata semua unit dan kode operasinya tanpa kode kendaraan.",
        )
    )
    instructions.append(
        (
            "Aktivitas",
            "Wajib",
            "Mobilisasi, atau Mobilisasi + lifting"
            + (f" (hanya untuk unit yang bisa lifting: {', '.join(lifting)})." if lifting else "."),
        )
    )
    instructions.append(
        (
            "Jarak Total (km)",
            "Wajib",
            "Jarak seluruh perjalanan, termasuk kembali. Lebih besar dari 0.",
        )
    )
    instructions.append(
        (
            "Jam Lifting",
            "Untuk lifting",
            "Total jam lifting sepanjang operasi. Kosongkan untuk Mobilisasi.",
        )
    )
    instructions.append(
        (
            "Urutan Pemberhentian",
            "Opsional",
            "Lokasi berurutan dipisah >, misalnya Depo > Site A > Depo.",
        )
    )
    instructions.append(
        (
            "Hasil",
            "Informasi",
            "Setiap baris yang valid mendapat kode operasi, estimasi kebutuhan BBM, "
            "dan alokasi rekomendasi. Baris yang bermasalah disisihkan beserta alasannya.",
        )
    )
    instructions.column_dimensions["A"].width = 24
    instructions.column_dimensions["B"].width = 16
    instructions.column_dimensions["C"].width = 96
    instructions.freeze_panes = "A3"

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _style_header(worksheet: Worksheet) -> None:
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="185C43")
