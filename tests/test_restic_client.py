import io
import threading

import pytest

from orpheus import restic_client as rc


class FakeProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def fake_factory(process, capture):
    def factory(command, **kwargs):
        capture["command"] = command
        capture["kwargs"] = kwargs
        return process
    return factory


def test_discover_hosts_uses_immediate_directories_only(tmp_path):
    (tmp_path / "zeta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "not-a-host.txt").write_text("x", encoding="utf-8")
    assert rc.discover_hosts(str(tmp_path)) == ["Alpha", "zeta"]


def test_discover_hosts_classifies_unreachable_path(tmp_path):
    with pytest.raises(rc.ResticError) as caught:
        rc.discover_hosts(str(tmp_path / "fehlt"))
    assert caught.value.kind in {"network", "missing", "restic"}
    assert "nicht erreichbar" in caught.value.user_message() or "nicht gefunden" in caught.value.user_message()


def test_argument_builders_preserve_windows_repo_and_make_exact_include():
    repo = r"\\nas\Backup Ablage\HOST-Ä"
    assert rc.build_snapshots_args(repo) == ["-r", repo, "snapshots", "--json"]
    args = rc.build_restore_args(repo, "abc12345", "/Daten/a*.txt", r"C:\Staging Lauf")
    assert args == [
        "-r", repo, "restore", "abc12345", "--target", r"C:\Staging Lauf", "--json",
        "--include", "/Daten/a[*].txt",
    ]
    assert "--include" not in rc.build_restore_args(repo, "abc12345", "", r"C:\Staging")


def test_snapshot_parser_and_ls_direct_children():
    snapshots = rc.parse_snapshot_list('[{"id":"abc","time":"2025-01-01T00:00:00Z"}]')
    assert snapshots[0]["id"] == "abc"
    lines = "\n".join((
        '{"struct_type":"snapshot","id":"abc"}',
        '{"struct_type":"node","path":"/foo","type":"dir"}',
        '{"struct_type":"node","path":"/foo/bar.txt","type":"file"}',
        '{"struct_type":"node","path":"/other.txt","type":"file"}',
    ))
    assert [item["path"] for item in rc.parse_ls_json_lines(lines, "/")] == ["/foo", "/other.txt"]
    assert [item["path"] for item in rc.parse_ls_json_lines(lines, "/foo")] == ["/foo/bar.txt"]


def test_parsers_reject_malformed_or_wrong_shape():
    with pytest.raises(rc.ResticError):
        rc.parse_snapshot_list("{}")
    with pytest.raises(rc.ResticError):
        rc.parse_ls_json_lines("not-json", "/")


def test_progress_parser():
    event = rc.parse_progress_line(
        '{"message_type":"status","percent_done":0.25,"files_restored":2,"total_files":8}'
    )
    assert event.message_type == "status"
    assert event.percent_done == 0.25
    assert "2 von 8" in event.message
    assert rc.parse_progress_line("kein json") is None


def test_runner_keeps_password_out_of_command_and_reports_progress():
    capture = {}
    process = FakeProcess(
        stdout='{"message_type":"status","percent_done":0.5,"message":"läuft"}\n',
        stderr="Hinweis\n",
    )
    progress = []
    result = rc.run_restic(
        ["-r", "repo", "restore", "abc"], "sehr-geheim",
        parse_progress=True, progress=lambda value, text: progress.append((value, text)),
        popen_factory=fake_factory(process, capture), binary="restic-test.exe",
    )
    assert "sehr-geheim" not in capture["command"]
    assert capture["kwargs"]["env"]["RESTIC_PASSWORD"] == "sehr-geheim"
    assert capture["kwargs"]["shell"] is False
    assert result.warnings == ("Hinweis",)
    assert progress == [(0.5, "läuft")]


@pytest.mark.parametrize(
    ("stderr", "kind"),
    [
        ("wrong password or no key found", "password"),
        ("repository is already locked", "locked"),
        ("no space left on device", "space"),
        ("Access is denied", "permission"),
    ],
)
def test_nonzero_exitcode_is_classified(stderr, kind):
    process = FakeProcess(stderr=stderr, returncode=1)
    with pytest.raises(rc.ResticError) as caught:
        rc.run_restic(
            ["snapshots"], "pw", popen_factory=fake_factory(process, {}), binary="fake.exe",
        )
    assert caught.value.returncode == 1
    assert caught.value.kind == kind


def test_json_error_event_is_partial_failure_even_with_exitcode_zero():
    process = FakeProcess(stdout='{"message_type":"error","message":"one file failed"}\n')
    with pytest.raises(rc.ResticError):
        rc.run_restic(
            ["restore"], "pw", parse_progress=True,
            popen_factory=fake_factory(process, {}), binary="fake.exe",
        )


def test_pre_cancelled_process_is_terminated():
    process = FakeProcess(stdout="")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(rc.OperationCancelled):
        rc.run_restic(
            ["snapshots"], "pw", cancel_event=cancel,
            popen_factory=fake_factory(process, {}), binary="fake.exe",
        )
    assert process.terminated
