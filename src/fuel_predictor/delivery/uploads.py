"""Reading an uploaded file no further than its limit.

A sheet is refused above 10 MB, but it was read whole into memory first,
however large it was. Reading one byte past the limit is enough for the
reader to refuse it as too large, and nothing more is ever held.
"""

from fastapi import UploadFile

from fuel_predictor.infrastructure.historical_source_reader import MAX_UPLOAD_BYTES


async def read_sheet(file: UploadFile) -> bytes:
    return await file.read(MAX_UPLOAD_BYTES + 1)


async def read_bounded(file: UploadFile, limit: int) -> bytes:
    return await file.read(limit + 1)
