"""Password hashing with `hashlib.scrypt` (ADR 0008).

The cost parameters are stored inside each hash string, so raising them later
only affects newly written hashes and never invalidates existing ones.
"""

import hmac
from base64 import b64decode, b64encode
from dataclasses import dataclass
from hashlib import scrypt
from secrets import token_bytes

_ALGORITHM = "scrypt"
_SALT_BYTES = 16
_DERIVED_KEY_BYTES = 32

# 128 * n * r bytes of memory, i.e. 16 MiB per verification at these values.
_DEFAULT_COST = 2**14
_DEFAULT_BLOCK_SIZE = 8
_DEFAULT_PARALLELISM = 1


class PasswordHashFormatError(ValueError):
    """A stored hash could not be parsed, so no password can be verified against it."""


@dataclass(frozen=True, slots=True)
class ScryptPasswordHasher:
    cost: int = _DEFAULT_COST
    block_size: int = _DEFAULT_BLOCK_SIZE
    parallelism: int = _DEFAULT_PARALLELISM

    def hash(self, password: str) -> str:
        salt = token_bytes(_SALT_BYTES)
        derived = self._derive(password, salt, self.cost, self.block_size, self.parallelism)
        return "$".join(
            (
                _ALGORITHM,
                str(self.cost),
                str(self.block_size),
                str(self.parallelism),
                _encode(salt),
                _encode(derived),
            )
        )

    def verify(self, password: str, stored_hash: str) -> bool:
        algorithm, cost, block_size, parallelism, salt, expected = _parse(stored_hash)
        if algorithm != _ALGORITHM:
            raise PasswordHashFormatError(f"Algoritma kata sandi tidak dikenali: {algorithm}")
        candidate = self._derive(password, salt, cost, block_size, parallelism)
        return hmac.compare_digest(candidate, expected)

    def needs_rehash(self, stored_hash: str) -> bool:
        _, cost, block_size, parallelism, _, _ = _parse(stored_hash)
        return (cost, block_size, parallelism) != (self.cost, self.block_size, self.parallelism)

    @staticmethod
    def _derive(password: str, salt: bytes, cost: int, block_size: int, parallelism: int) -> bytes:
        return scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=cost,
            r=block_size,
            p=parallelism,
            dklen=_DERIVED_KEY_BYTES,
            maxmem=128 * cost * block_size * 2,
        )


def _parse(stored_hash: str) -> tuple[str, int, int, int, bytes, bytes]:
    parts = stored_hash.split("$")
    if len(parts) != 6:
        raise PasswordHashFormatError("Format hash kata sandi tidak valid.")
    algorithm, cost, block_size, parallelism, salt, derived = parts
    try:
        return (
            algorithm,
            int(cost),
            int(block_size),
            int(parallelism),
            b64decode(salt),
            b64decode(derived),
        )
    except ValueError as error:
        raise PasswordHashFormatError("Format hash kata sandi tidak valid.") from error


def _encode(value: bytes) -> str:
    return b64encode(value).decode("ascii")
