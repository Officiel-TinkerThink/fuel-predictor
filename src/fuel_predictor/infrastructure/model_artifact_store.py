"""Where accepted model packages are kept on disk (ADR 0009, ADR 0010).

Storage paths are generated here from the *validated* model version and
never taken from the archive, which is why a hostile member name cannot
reach the filesystem. Retained artefacts are a correctness concern, not just
disk hygiene: rollback can only return to a version whose bytes still exist.
"""

import re
from dataclasses import dataclass
from pathlib import Path

_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


class ArtifactStorageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FilesystemModelArtifactStore:
    root: Path

    def store(self, model_version: str, members: dict[str, bytes]) -> Path:
        """Write one package's members under a directory named for its version.

        The version has already passed the manifest schema's pattern, but it
        is re-checked here rather than trusted: this function is what turns a
        string into a filesystem path, so it owns that decision regardless of
        what validated it earlier.
        """
        if not _SAFE_VERSION.match(model_version):
            raise ArtifactStorageError(
                f"Versi model '{model_version}' tidak aman untuk dijadikan nama direktori."
            )

        destination = self.root / model_version
        destination.mkdir(parents=True, exist_ok=True)
        for name, payload in members.items():
            member_path = destination / Path(name).name
            member_path.write_bytes(payload)
        return destination

    def path_for(self, model_version: str) -> Path:
        return self.root / model_version

    def exists(self, model_version: str) -> bool:
        return self.path_for(model_version).is_dir()
