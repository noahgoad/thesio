"""Local integrity checks for reproducible research bundles."""

from hashlib import sha256
from pathlib import Path
import re


def verify_bundle(root: Path, expected: dict[str, str]) -> list[str]:
    root = Path(root).resolve()
    if not expected:
        raise ValueError("EMPTY_RELEASE_MANIFEST")
    checked = []
    for relative, digest in expected.items():
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError("INVALID_BUNDLE_PATH")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("INVALID_BUNDLE_PATH")
        lowered_parts = {part.lower() for part in relative.replace("\\", "/").split("/")}
        if any(part == ".env" or part.startswith(".env.") for part in lowered_parts) or path.suffix.lower() in {".pem", ".key"}:
            raise ValueError("SECRET_FILE_FORBIDDEN")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise ValueError("BUNDLE_DIGEST_INVALID")
        if sha256(path.read_bytes()).hexdigest() != digest.lower():
            raise ValueError("BUNDLE_HASH_MISMATCH")
        checked.append(relative.replace("\\", "/"))
    return sorted(checked)
