"""Bounded, traversal-safe reading of an uploaded model package ZIP (ADR 0009).

The archive is untrusted input. Everything here exists so that a hostile
upload fails with a clear validation error instead of exhausting memory,
filling the disk, or writing outside the package root.
"""

import ntpath
import posixpath
import zipfile
from collections.abc import Mapping
from io import BytesIO

from fuel_predictor.application.model_package_ingestion import ModelPackageArchiveLimits
from fuel_predictor.domain.model_package import ModelPackageValidationError


class ZipModelPackageArchiveReader:
    def __init__(self, limits: ModelPackageArchiveLimits) -> None:
        self._limits = limits

    def read_members(self, archive_bytes: bytes) -> Mapping[str, bytes]:
        if len(archive_bytes) > self._limits.max_archive_bytes:
            raise _error(
                f"Arsip terlalu besar: maksimal {self._limits.max_archive_bytes} byte."
            )

        try:
            with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
                return self._read_all(archive)
        except zipfile.BadZipFile as error:
            raise _error("Berkas bukan arsip ZIP yang valid.") from error

    def _read_all(self, archive: zipfile.ZipFile) -> dict[str, bytes]:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if len(entries) > self._limits.max_member_count:
            raise _error(
                f"Arsip berisi terlalu banyak berkas: maksimal {self._limits.max_member_count}."
            )

        members: dict[str, bytes] = {}
        total_read = 0
        for info in entries:
            name = _safe_member_name(info.filename)
            remaining = self._limits.max_extracted_bytes - total_read
            payload = self._read_one(archive, info, remaining)
            total_read += len(payload)
            members[name] = payload
        return members

    def _read_one(
        self, archive: zipfile.ZipFile, info: zipfile.ZipInfo, remaining: int
    ) -> bytes:
        # Read one byte past what's allowed: if we get it, the member is over
        # the limit. The zip header's declared `file_size` is attacker-
        # controlled, so it is never trusted as the bound — only as an early
        # rejection for the obvious cases.
        with archive.open(info) as handle:
            payload = handle.read(remaining + 1)

        if len(payload) > remaining:
            raise _error(
                "Total isi arsip terlalu besar: maksimal "
                f"{self._limits.max_extracted_bytes} byte setelah diekstrak."
            )
        if info.compress_size > 0:
            ratio = len(payload) / info.compress_size
            if ratio > self._limits.max_compression_ratio:
                raise _error(
                    f"Rasio kompresi berkas '{info.filename}' mencurigakan "
                    f"({ratio:.0f}:1); maksimal {self._limits.max_compression_ratio}:1."
                )
        return payload


def _safe_member_name(raw_name: str) -> str:
    """Reject absolute paths, drive letters, and anything escaping the package root.

    Checks both POSIX and Windows separator conventions, because a ZIP made on
    either platform can be uploaded to a server running the other.
    """
    if not raw_name or raw_name.strip() != raw_name:
        raise _error(f"Nama berkas dalam arsip tidak valid: '{raw_name}'.")
    if posixpath.isabs(raw_name) or ntpath.isabs(raw_name) or ntpath.splitdrive(raw_name)[0]:
        raise _error(f"Nama berkas dalam arsip tidak boleh absolut: '{raw_name}'.")

    segments = [segment for segment in raw_name.replace("\\", "/").split("/") if segment]
    if any(segment == ".." for segment in segments):
        raise _error(f"Nama berkas dalam arsip keluar dari paket: '{raw_name}'.")
    if not segments:
        raise _error(f"Nama berkas dalam arsip tidak valid: '{raw_name}'.")
    return "/".join(segments)


def _error(message: str) -> ModelPackageValidationError:
    return ModelPackageValidationError([("archive", message)])
