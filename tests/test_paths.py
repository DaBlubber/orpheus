import os

import pytest

from orpheus.paths import (
    PathValidationError,
    is_within,
    join_repo_path,
    literal_restic_pattern,
    normalize_snapshot_path,
    windows_extended_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"C:\Benutzer\Jörg\Datei mit Leerzeichen.txt", "/C:/Benutzer/Jörg/Datei mit Leerzeichen.txt"),
        ("/etc//hosts", "/etc/hosts"),
        ("foo/bar/", "/foo/bar"),
        ("", ""),
    ],
)
def test_snapshot_path_normalization(raw, expected):
    assert normalize_snapshot_path(raw) == expected


@pytest.mark.parametrize("raw", ["../secret", "/a/../b", "bad\x00path", "x\npath"])
def test_snapshot_path_rejects_unsafe_segments(raw):
    with pytest.raises(PathValidationError):
        normalize_snapshot_path(raw)


def test_literal_include_escapes_glob_metacharacters():
    assert literal_restic_pattern("/data/a*?[x].txt") == "/data/a[*][?][[]x].txt"


def test_repo_path_only_accepts_direct_hostname(tmp_path):
    assert join_repo_path(str(tmp_path), "HOST-01") == os.path.join(str(tmp_path), "HOST-01")
    with pytest.raises(PathValidationError):
        join_repo_path(str(tmp_path), r"..\anderes-repo")


def test_containment_and_long_path_helper(tmp_path):
    child = tmp_path / "a" / "b"
    assert is_within(str(child), str(tmp_path))
    assert not is_within(str(tmp_path), str(child))
    extended = windows_extended_path(str(child))
    if os.name == "nt":
        assert extended.startswith("\\\\?\\")
    else:
        assert extended == str(child)
