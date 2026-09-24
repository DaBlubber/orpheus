import json
import os
import threading

import pytest

from orpheus.restic_client import OperationCancelled
from orpheus.restore_service import (
    MARKER_NAME,
    CollisionError,
    StagingError,
    apply_transfer_plan,
    build_transfer_plan,
    create_staging_session,
    discover_staging_sessions,
    discard_staging,
    load_staging_session,
    update_staging_status,
)


def make_session(tmp_path):
    root = tmp_path / "staging"
    return create_staging_session(str(root), "abcdef123456", "/Daten", r"Z:\Repo\HOST")


def test_staging_sessions_are_fresh_marked_and_loadable(tmp_path):
    first = make_session(tmp_path)
    second = make_session(tmp_path)
    assert first.path != second.path
    assert os.path.isfile(os.path.join(first.path, MARKER_NAME))
    loaded = load_staging_session(first.path, first.root)
    assert loaded.snapshot_id == "abcdef123456"
    completed = update_staging_status(loaded, "complete")
    assert load_staging_session(first.path, first.root).status == "complete"
    assert completed.status == "complete"
    discovered = discover_staging_sessions(first.root)
    assert {item.path for item in discovered} == {first.path, second.path}


def test_unmarked_or_outside_folder_is_never_discarded(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(StagingError):
        load_staging_session(str(outside), str(tmp_path / "staging"))
    assert outside.exists()


def test_discard_removes_only_session_and_keeps_root(tmp_path):
    session = make_session(tmp_path)
    root = session.root
    discard_staging(session)
    assert not os.path.exists(session.path)
    assert os.path.isdir(root)


def test_transfer_plan_copies_content_but_not_marker(tmp_path):
    session = make_session(tmp_path)
    source = os.path.join(session.content_path, "Ordner")
    os.makedirs(source)
    with open(os.path.join(source, "unicode-ä.txt"), "w", encoding="utf-8") as handle:
        handle.write("Inhalt")
    destination = tmp_path / "ziel"
    plan = build_transfer_plan(session.content_path, str(destination))
    assert plan.total_files == 1
    assert plan.total_bytes == len("Inhalt".encode("utf-8"))
    assert not any(item.relative_path == MARKER_NAME for item in plan.items)
    result = apply_transfer_plan(plan)
    assert result.files_copied == 1
    assert (destination / "Ordner" / "unicode-ä.txt").read_text(encoding="utf-8") == "Inhalt"


def test_collisions_require_explicit_overwrite(tmp_path):
    session = make_session(tmp_path)
    staged_file = os.path.join(session.content_path, "same.txt")
    with open(staged_file, "w", encoding="utf-8") as handle:
        handle.write("neu")
    destination = tmp_path / "ziel"
    destination.mkdir()
    target = destination / "same.txt"
    target.write_text("alt", encoding="utf-8")
    plan = build_transfer_plan(session.content_path, str(destination))
    assert plan.collisions == ("same.txt",)
    with pytest.raises(CollisionError):
        apply_transfer_plan(plan)
    assert target.read_text(encoding="utf-8") == "alt"
    result = apply_transfer_plan(plan, overwrite=True)
    assert result.overwritten == 1
    assert target.read_text(encoding="utf-8") == "neu"
    assert not list(destination.glob("*.orpheus-*.tmp"))


def test_pre_cancelled_transfer_does_not_copy_file(tmp_path):
    session = make_session(tmp_path)
    with open(os.path.join(session.content_path, "file.bin"), "wb") as handle:
        handle.write(b"x" * 16)
    destination = tmp_path / "ziel"
    plan = build_transfer_plan(session.content_path, str(destination))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OperationCancelled):
        apply_transfer_plan(plan, cancel_event=cancel)
    assert not (destination / "file.bin").exists()


def test_destination_inside_staging_is_rejected(tmp_path):
    session = make_session(tmp_path)
    with pytest.raises(StagingError):
        build_transfer_plan(session.content_path, os.path.join(session.content_path, "ziel"))
