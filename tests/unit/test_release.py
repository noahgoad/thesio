from hashlib import sha256

import pytest

from narrative_research_desk.release import verify_bundle


def test_bundle_integrity(tmp_path):
    (tmp_path / "report.json").write_bytes(b"{}")
    assert verify_bundle(tmp_path, {"report.json": sha256(b"{}").hexdigest()}) == ["report.json"]
    with pytest.raises(ValueError, match="BUNDLE_HASH_MISMATCH"):
        verify_bundle(tmp_path, {"report.json": "a" * 64})


@pytest.mark.parametrize("name", [".env", "private.pem", "secret.key"])
def test_secret_files_rejected(tmp_path, name):
    path = tmp_path / name
    path.write_text("not a real secret", encoding="utf-8")
    digest = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="SECRET_FILE_FORBIDDEN"):
        verify_bundle(tmp_path, {name: digest})


def test_path_escape_missing_files_and_empty_manifest_rejected(tmp_path):
    with pytest.raises(ValueError, match="INVALID_BUNDLE_PATH"):
        verify_bundle(tmp_path, {"../outside": "a" * 64})
    with pytest.raises(ValueError, match="INVALID_BUNDLE_PATH"):
        verify_bundle(tmp_path, {"missing.json": "a" * 64})
    with pytest.raises(ValueError, match="EMPTY_RELEASE_MANIFEST"):
        verify_bundle(tmp_path, {})
