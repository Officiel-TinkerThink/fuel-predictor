"""Archive-handling safety for uploaded model packages (ADR 0009, plan steps 1-3).

These are adversarial tests: the archive arrives from outside production and
is assumed hostile until proven otherwise.
"""

import zipfile
from hashlib import sha256
from io import BytesIO

import pytest

from fuel_predictor.application.model_package_ingestion import ModelPackageArchiveLimits
from fuel_predictor.domain.model_package import ModelPackageValidationError
from fuel_predictor.infrastructure.zip_model_package_archive import ZipModelPackageArchiveReader


def _zip_of(members: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _reader(**overrides: int) -> ZipModelPackageArchiveReader:
    settings: dict[str, int] = {
        "max_archive_bytes": 1_000_000,
        "max_extracted_bytes": 4_000_000,
        "max_member_count": 16,
        "max_compression_ratio": 100,
    }
    settings.update(overrides)
    return ZipModelPackageArchiveReader(ModelPackageArchiveLimits(**settings))


def test_reads_every_member_of_a_well_formed_archive() -> None:
    members = _reader().read_members(
        _zip_of({"manifest.json": b'{"a": 1}', "model.onnx": b"binary-ish"})
    )

    assert members == {"manifest.json": b'{"a": 1}', "model.onnx": b"binary-ish"}


def test_directory_entries_are_ignored_rather_than_returned_as_empty_members() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("nested/", b"")
        archive.writestr("manifest.json", b"{}")

    members = _reader().read_members(buffer.getvalue())

    assert set(members) == {"manifest.json"}


@pytest.mark.parametrize(
    "hostile_name",
    [
        "../escape.json",
        "../../etc/passwd",
        "nested/../../escape.json",
        "/absolute.json",
        "//server/share/file.json",
        "C:/windows/system32/evil.dll",
        "C:\\windows\\system32\\evil.dll",
        "..\\escape.json",
        "nested\\..\\..\\escape.json",
    ],
)
def test_member_names_that_escape_the_package_are_rejected(hostile_name: str) -> None:
    with pytest.raises(ModelPackageValidationError) as excinfo:
        _reader().read_members(_zip_of({hostile_name: b"payload"}))

    assert any(field == "archive" for field, _message in excinfo.value.errors)


def test_archive_larger_than_the_limit_is_rejected_before_being_opened() -> None:
    reader = _reader(max_archive_bytes=64)

    with pytest.raises(ModelPackageValidationError) as excinfo:
        reader.read_members(_zip_of({"manifest.json": b"x" * 4096}))

    assert any("besar" in message.lower() for _field, message in excinfo.value.errors)


def test_too_many_members_is_rejected() -> None:
    reader = _reader(max_member_count=3)

    with pytest.raises(ModelPackageValidationError):
        reader.read_members(_zip_of({f"file-{index}.json": b"{}" for index in range(4)}))


def test_total_extracted_size_beyond_the_limit_is_rejected() -> None:
    reader = _reader(max_extracted_bytes=1024)

    with pytest.raises(ModelPackageValidationError) as excinfo:
        reader.read_members(_zip_of({"big.bin": b"x" * 8192}))

    assert any("besar" in message.lower() for _field, message in excinfo.value.errors)


def test_highly_compressible_zip_bomb_is_rejected_by_the_compression_ratio_limit() -> None:
    # A megabyte of zeroes compresses to well under 1% of its size, so this
    # trips the ratio limit long before the absolute extracted-size limit.
    reader = _reader(max_extracted_bytes=100_000_000, max_compression_ratio=10)

    with pytest.raises(ModelPackageValidationError) as excinfo:
        reader.read_members(_zip_of({"bomb.bin": b"\0" * 1_000_000}))

    assert any(field == "archive" for field, _message in excinfo.value.errors)


def test_an_oversized_member_is_rejected_by_our_extracted_size_limit() -> None:
    """An honestly-declared, oversized member trips our limit, not zipfile's checks.

    Asserts the *specific* size-limit message rather than just "some error",
    so this can't start passing for an unrelated reason (a malformed-archive
    rejection, say) if the reader changes.

    Note what this does *not* prove: that reading is bounded rather than
    read-in-full-then-rejected. Both implementations pass this test. The
    bounded read in `_read_one` is a memory-exhaustion defence whose absence
    a unit test can't practically detect — see the comment there for why it
    is written that way.
    """
    # Incompressible content, so the compression-ratio limit can't be what fires.
    payload = bytes(index % 251 for index in range(400_000))
    reader = _reader(max_extracted_bytes=50_000, max_archive_bytes=10_000_000)

    with pytest.raises(ModelPackageValidationError) as excinfo:
        reader.read_members(_zip_of({"honest-but-huge.bin": payload}))

    assert any(
        "setelah diekstrak" in message for _field, message in excinfo.value.errors
    ), excinfo.value.errors


def test_an_archive_whose_declared_size_was_tampered_with_is_rejected() -> None:
    """A size lie makes the archive internally inconsistent, and that is refused.

    `zipfile` catches this itself via its CRC/size consistency check rather
    than our limits — worth pinning so the behaviour doesn't silently change
    to something permissive under a future Python.
    """
    payload = b"x" * 200_000
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("liar.bin", payload)
    tampered = buffer.getvalue().replace(
        len(payload).to_bytes(4, "little"), (16).to_bytes(4, "little")
    )

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _reader(max_extracted_bytes=50_000).read_members(tampered)

    assert any(field == "archive" for field, _message in excinfo.value.errors)


def test_a_file_that_is_not_a_zip_is_rejected_with_a_readable_message() -> None:
    with pytest.raises(ModelPackageValidationError) as excinfo:
        _reader().read_members(b"this is definitely not a zip archive")

    assert any(field == "archive" for field, _message in excinfo.value.errors)


def test_checksums_are_verified_against_the_manifest() -> None:
    from fuel_predictor.application.model_package_ingestion import verify_member_checksums

    payload = b"model bytes"
    digest = sha256(payload).hexdigest()

    verify_member_checksums({"model.onnx": payload}, {"model.onnx": digest})

    with pytest.raises(ModelPackageValidationError) as excinfo:
        verify_member_checksums({"model.onnx": b"tampered"}, {"model.onnx": digest})

    assert any(field == "package_checksums" for field, _message in excinfo.value.errors)


def test_a_member_present_in_the_archive_but_absent_from_the_manifest_is_rejected() -> None:
    from fuel_predictor.application.model_package_ingestion import verify_member_checksums

    payload = b"model bytes"
    with pytest.raises(ModelPackageValidationError) as excinfo:
        verify_member_checksums(
            {"model.onnx": payload, "surprise.sh": b"rm -rf /"},
            {"model.onnx": sha256(payload).hexdigest()},
        )

    assert any(
        "surprise.sh" in message for _field, message in excinfo.value.errors
    )


def test_a_member_declared_in_the_manifest_but_missing_from_the_archive_is_rejected() -> None:
    from fuel_predictor.application.model_package_ingestion import verify_member_checksums

    with pytest.raises(ModelPackageValidationError) as excinfo:
        verify_member_checksums({}, {"model.onnx": "a" * 64})

    assert any("model.onnx" in message for _field, message in excinfo.value.errors)
