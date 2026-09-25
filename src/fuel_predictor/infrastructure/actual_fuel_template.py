import csv
from collections.abc import Sequence
from io import BytesIO, StringIO
from typing import cast

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

BULK_ACTUAL_FUEL_TEMPLATE_HEADERS = (
    "Kode Operasi (wajib)",
    "Bahan Bakar Aktual (L) (wajib)",
    "Diukur dengan (opsional)",
)
# The same words, in the same order, as the form and the slip.
MEASUREMENT_CHOICES = ("Meter BBM", "Nota", "Catatan manual")
# Rows the checks cover; far more than a sheet of waiting operations.
_ROWS = 2000


def csv_template() -> bytes:
    output = StringIO(newline="")
    csv.writer(output).writerow(BULK_ACTUAL_FUEL_TEMPLATE_HEADERS)
    return output.getvalue().encode("utf-8-sig")


def xlsx_template() -> bytes:
    workbook = Workbook()
    worksheet = cast(Worksheet, workbook.active)
    worksheet.title = "Bahan Bakar Aktual"
    worksheet.append(BULK_ACTUAL_FUEL_TEMPLATE_HEADERS)
    _style_header(worksheet)
    _guard_entries(worksheet)
    for column, width in zip("ABC", (42, 34, 32), strict=True):
        worksheet.column_dimensions[column].width = width
    worksheet.freeze_panes = "A2"

    instructions = workbook.create_sheet("Petunjuk")
    instructions.append(("Kolom", "Status", "Petunjuk"))
    _style_header(instructions)
    instructions.append(
        (
            "Kode Operasi",
            "Wajib",
            "Kode yang dicatat saat estimasi dibuat, misalnya 260924-0914-VT-P410-VT01. "
            "Huruf besar/kecil dan spasi tidak berpengaruh.",
        )
    )
    instructions.append(
        ("Bahan Bakar Aktual (L)", "Wajib", "Liter yang benar-benar terpakai, lebih dari 0.")
    )
    instructions.append(
        ("Diukur dengan", "Opsional", "Pilih Meter BBM, Nota, atau Catatan manual.")
    )
    instructions.append(
        (
            "Hasil",
            "Informasi",
            "Baris yang bermasalah disisihkan beserta alasannya; baris lainnya tetap disimpan.",
        )
    )
    instructions.column_dimensions["A"].width = 30
    instructions.column_dimensions["B"].width = 18
    instructions.column_dimensions["C"].width = 90
    instructions.freeze_panes = "A2"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


# Beside the columns the import reads, what a person needs to recognise the
# operation. "(info)" keeps them out of the importer's header matching.
WAITING_INFO_HEADERS = (
    "Kendaraan (info)",
    "Diprediksi (info)",
    "Rute (info)",
    "Alokasi (L) (info)",
)


def waiting_xlsx(rows: Sequence[tuple[str, str, str, str, float]]) -> bytes:
    """The operations still waiting for actual fuel, as a sheet to fill in.

    Each row is (code, vehicle, predicted at, route, allocation). The litres
    and measurement columns are left empty; uploaded back through the bulk
    import, rows still empty are skipped as not yet filled.
    """
    workbook = Workbook()
    worksheet = cast(Worksheet, workbook.active)
    worksheet.title = "Bahan Bakar Aktual"
    worksheet.append((*BULK_ACTUAL_FUEL_TEMPLATE_HEADERS, *WAITING_INFO_HEADERS))
    _style_header(worksheet)
    for code, vehicle, predicted_at, route, allocation in rows:
        worksheet.append((code, None, None, vehicle, predicted_at, route, round(allocation, 2)))
    _guard_entries(worksheet)
    for column, width in zip("ABCDEFG", (30, 30, 28, 22, 18, 36, 18), strict=True):
        worksheet.column_dimensions[column].width = width
    worksheet.freeze_panes = "B2"

    instructions = workbook.create_sheet("Petunjuk")
    instructions.append(("Langkah", "Petunjuk"))
    _style_header(instructions)
    instructions.append(("1", "Isi kolom Bahan Bakar Aktual (L) untuk operasi yang sudah selesai."))
    instructions.append(
        ("2", "Diukur dengan: pilih Meter BBM, Nota, atau Catatan manual; kosong juga boleh.")
    )
    instructions.append(
        ("3", "Baris yang belum diisi biarkan kosong: saat diunggah, baris itu dilewati.")
    )
    instructions.append(("4", "Unggah berkas ini di menu Impor Massal (BBM Aktual)."))
    instructions.append(
        ("Info", "Kolom bertanda (info) hanya untuk mengenali operasi; tidak dibaca.")
    )
    instructions.column_dimensions["A"].width = 10
    instructions.column_dimensions["B"].width = 90
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _guard_entries(worksheet: Worksheet) -> None:
    """Excel refuses a word where litres go and offers the three ways of
    measuring as a list, so mistakes are caught while typing, not on upload."""
    litres = DataValidation(type="decimal", operator="greaterThan", formula1="0")
    litres.error = "Isi liter yang terpakai: angka lebih dari 0."
    litres.showErrorMessage = True
    measured = DataValidation(
        type="list", formula1='"' + ",".join(MEASUREMENT_CHOICES) + '"', allow_blank=True
    )
    measured.error = "Pilih Meter BBM, Nota, atau Catatan manual."
    measured.showErrorMessage = True
    worksheet.add_data_validation(litres)
    worksheet.add_data_validation(measured)
    litres.add(f"B2:B{_ROWS}")
    measured.add(f"C2:C{_ROWS}")


def _style_header(worksheet: Worksheet) -> None:
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="185C43")
