"""Robust, cancellable process layer for the Windows restic CLI."""

from __future__ import annotations

import json
import os
import posixpath
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .paths import PathValidationError, join_repo_path, literal_restic_pattern, normalize_snapshot_path


ProgressCallback = Callable[[float | None, str], None]


class OperationCancelled(RuntimeError):
    """A running operation was explicitly cancelled."""


class ResticError(RuntimeError):
    """A classified restic/repository error with a recommended action."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "restic",
        detail: str = "",
        action: str = "",
        returncode: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.detail = detail
        self.action = action
        self.returncode = returncode

    def user_message(self) -> str:
        parts = [str(self)]
        if self.action:
            parts.append(self.action)
        if self.detail and self.detail.strip() != str(self).strip():
            parts.append(f"Technical detail: {self.detail.strip()}")
        return "\n\n".join(parts)


@dataclass(frozen=True)
class ResticEvent:
    message_type: str
    percent_done: float | None
    message: str
    raw: dict


@dataclass(frozen=True)
class ResticRunResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    events: tuple[ResticEvent, ...]
    warnings: tuple[str, ...]


def app_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def restic_exe() -> str:
    candidates = [os.path.join(app_root(), "bin", "restic.exe")]
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), "bin", "restic.exe"))
    return next((candidate for candidate in candidates if os.path.exists(candidate)), "restic.exe")


def discover_hosts(backup_base_path: str) -> list[str]:
    """Returns the immediate repository subfolders without changing anything on the NAS."""

    base = (backup_base_path or "").strip()
    if not base:
        raise ResticError(
            "The backup base path is empty.", kind="repository",
            action="Choose the network drive or a UNC base path.",
        )
    try:
        with os.scandir(base) as entries:
            hosts = [entry.name for entry in entries if entry.is_dir()]
    except OSError as exc:
        raise _classify_failure(str(exc), returncode=None, fallback="The backup base path is not reachable.") from exc
    return sorted(hosts, key=str.casefold)


def discover_hosts_cancellable(backup_base_path: str, cancel_event: threading.Event) -> list[str]:
    """Wraps the non-cancellable Windows file system call in a daemon thread."""

    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def scan():
        try:
            result_queue.put((True, discover_hosts(backup_base_path)))
        except Exception as exc:
            result_queue.put((False, exc))

    threading.Thread(target=scan, name="Orpheus-Hostscan", daemon=True).start()
    while True:
        if cancel_event.is_set():
            raise OperationCancelled(
                "The host search was cancelled. A blocked Windows network access may still finish in the background."
            )
        try:
            success, value = result_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if success:
            return value
        raise value


def repo_path(backup_base_path: str, hostname: str) -> str:
    try:
        return join_repo_path(backup_base_path, hostname)
    except PathValidationError as exc:
        raise ResticError(str(exc), kind="path", action="Choose a host from the list.") from exc


def build_snapshots_args(repo: str) -> list[str]:
    return ["-r", repo, "snapshots", "--json"]


def build_ls_args(repo: str, snapshot_id: str, path: str = "/") -> list[str]:
    return ["-r", repo, "ls", "--json", _validate_snapshot_id(snapshot_id), normalize_snapshot_path(path, allow_empty=False)]


def build_dump_args(repo: str, snapshot_id: str, file_path: str) -> list[str]:
    return ["-r", repo, "dump", _validate_snapshot_id(snapshot_id), normalize_snapshot_path(file_path, allow_empty=False)]


def build_restore_args(repo: str, snapshot_id: str, include_path: str, target: str) -> list[str]:
    if not target or "\x00" in target:
        raise ResticError("The staging target path is invalid.", kind="path")
    args = ["-r", repo, "restore", _validate_snapshot_id(snapshot_id), "--target", target, "--json"]
    include = normalize_snapshot_path(include_path) if include_path else ""
    if include and include != "/":
        args.extend(["--include", literal_restic_pattern(include)])
    return args


def _validate_snapshot_id(snapshot_id: str) -> str:
    value = (snapshot_id or "").strip()
    if not value or value.startswith("-") or any(char in value for char in ("\x00", "\r", "\n", "/", "\\")):
        raise ResticError("The snapshot ID is invalid.", kind="path", action="Reload the snapshot list.")
    return value


def parse_snapshot_list(payload: str) -> list[dict]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ResticError(
            "restic did not return a valid snapshot list.", kind="json",
            detail=str(exc), action="Check the restic version and the repository, then reload.",
        ) from exc
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ResticError("The restic snapshot list has an unexpected format.", kind="json")
    return parsed


def parse_ls_json_lines(payload: str, requested_path: str) -> list[dict]:
    parent = normalize_snapshot_path(requested_path, allow_empty=False)
    nodes: list[dict] = []
    malformed: list[str] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            malformed.append(str(line_number))
            continue
        if not isinstance(item, dict) or item.get("struct_type") != "node":
            continue
        node_path = item.get("path")
        if not isinstance(node_path, str):
            continue
        try:
            normalized = normalize_snapshot_path(node_path, allow_empty=False)
        except PathValidationError:
            continue
        if normalized == parent:
            continue
        node_parent = posixpath.dirname(normalized.rstrip("/")) or "/"
        expected_parent = parent.rstrip("/") or "/"
        if node_parent == expected_parent:
            nodes.append(item)
    if malformed:
        raise ResticError(
            "The file list from restic was incomplete or corrupted.", kind="json",
            detail=f"Invalid JSON lines: {', '.join(malformed[:8])}",
            action="Check the network connection and reload the directory.",
        )
    return nodes


def parse_progress_line(line: str) -> ResticEvent | None:
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    message_type = str(value.get("message_type") or value.get("type") or value.get("struct_type") or "")
    if not message_type:
        return None
    percent = value.get("percent_done")
    try:
        percent_done = max(0.0, min(1.0, float(percent))) if percent is not None else None
    except (TypeError, ValueError):
        percent_done = None
    message = str(value.get("message") or value.get("error") or "")
    if not message and message_type == "status":
        files_done = value.get("files_restored", 0)
        total_files = value.get("total_files", 0)
        message = f"{files_done} of {total_files} files"
    if not message and message_type == "summary":
        message = "restic restore finished"
    return ResticEvent(message_type, percent_done, message, value)


def run_restic(
    args: Iterable[str],
    password: str,
    *,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    binary: str | None = None,
    parse_progress: bool = False,
    popen_factory=None,
) -> ResticRunResult:
    """Starts restic without a shell and drains stdout/stderr in parallel.

    The password only ever exists in a private copy of the child process
    environment. Neither the result nor any exception contains that environment.
    """

    argument_list = [str(item) for item in args]
    command = [binary or restic_exe(), *argument_list]
    environment = dict(os.environ)
    environment["RESTIC_PASSWORD"] = password
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    factory = popen_factory or subprocess.Popen
    try:
        process = factory(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            shell=False,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise _classify_failure(str(exc), returncode=None, fallback="restic could not be started.") from exc

    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def reader(name: str, stream):
        try:
            for line in iter(stream.readline, ""):
                output_queue.put((name, line))
        finally:
            output_queue.put((name, None))
            stream.close()

    threading.Thread(target=reader, args=("stdout", process.stdout), daemon=True).start()
    threading.Thread(target=reader, args=("stderr", process.stderr), daemon=True).start()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    events: list[ResticEvent] = []
    closed_streams: set[str] = set()
    cancelling = False
    cancel_started = 0.0

    while len(closed_streams) < 2 or process.poll() is None:
        if cancel_event is not None and cancel_event.is_set() and not cancelling:
            cancelling = True
            cancel_started = time.monotonic()
            try:
                process.terminate()
            except OSError:
                pass
        if cancelling and process.poll() is None and time.monotonic() - cancel_started > 3.0:
            try:
                process.kill()
            except OSError:
                pass
        try:
            stream_name, line = output_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            closed_streams.add(stream_name)
            continue
        if stream_name == "stdout":
            stdout_parts.append(line)
            if parse_progress:
                event = parse_progress_line(line)
                if event is not None:
                    events.append(event)
                    if progress and (event.percent_done is not None or event.message):
                        progress(event.percent_done, event.message or "Restore running ...")
        else:
            stderr_parts.append(line)

    returncode = process.wait()
    if cancelling:
        raise OperationCancelled("The running restic operation was cancelled.")
    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts).strip()
    error_events = [event.message for event in events if event.message_type.lower() in {"error", "fatal"}]
    if returncode != 0 or error_events:
        detail = stderr or "\n".join(message for message in error_events if message)
        fallback = "restic did not complete the operation." if error_events else "restic aborted the operation."
        raise _classify_failure(detail, returncode=returncode, fallback=fallback)
    warnings = tuple(line.strip() for line in stderr.splitlines() if line.strip())
    return ResticRunResult(tuple(argument_list), returncode, stdout, stderr, tuple(events), warnings)


def list_snapshots(repo: str, password: str, *, cancel_event: threading.Event | None = None) -> list[dict]:
    result = run_restic(build_snapshots_args(repo), password, cancel_event=cancel_event)
    return parse_snapshot_list(result.stdout)


def list_snapshot_dir(
    repo: str,
    password: str,
    snapshot_id: str,
    path: str = "/",
    *,
    cancel_event: threading.Event | None = None,
) -> list[dict]:
    normalized = normalize_snapshot_path(path, allow_empty=False)
    result = run_restic(build_ls_args(repo, snapshot_id, normalized), password, cancel_event=cancel_event)
    return parse_ls_json_lines(result.stdout, normalized)


def dump_file(
    repo: str,
    password: str,
    snapshot_id: str,
    file_path: str,
    max_bytes: int = 65536,
    *,
    cancel_event: threading.Event | None = None,
) -> bytes:
    """Reads at most `max_bytes`; a larger dump is terminated deliberately."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    command = [restic_exe(), *build_dump_args(repo, snapshot_id, file_path)]
    environment = dict(os.environ)
    environment["RESTIC_PASSWORD"] = password
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
            shell=False, creationflags=creationflags,
        )
    except OSError as exc:
        raise _classify_failure(str(exc), returncode=None, fallback="restic could not be started.") from exc

    stderr_parts: list[bytes] = []
    stdout_queue: queue.Queue[bytes | None] = queue.Queue()

    def read_stdout():
        try:
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                stdout_queue.put(chunk)
        finally:
            stdout_queue.put(None)

    def read_stderr():
        stderr_parts.append(process.stderr.read())

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    data = bytearray()
    truncated = False
    cancelled = False
    terminating_since: float | None = None
    stdout_closed = False
    while not stdout_closed:
        if cancel_event is not None and cancel_event.is_set() and not cancelled:
            cancelled = True
            terminating_since = time.monotonic()
            try:
                process.terminate()
            except OSError:
                pass
        if terminating_since is not None and process.poll() is None and time.monotonic() - terminating_since > 3:
            try:
                process.kill()
            except OSError:
                pass
        try:
            chunk = stdout_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if chunk is None:
            stdout_closed = True
            continue
        if not truncated:
            data.extend(chunk[: max_bytes + 1 - len(data)])
            if len(data) > max_bytes:
                truncated = True
                terminating_since = time.monotonic()
                try:
                    process.terminate()
                except OSError:
                    pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    process.stdout.close()
    process.stderr.close()
    if cancelled:
        raise OperationCancelled("The preview was cancelled.")
    if not truncated and process.returncode != 0:
        detail = b"".join(stderr_parts).decode("utf-8", errors="replace").strip()
        raise _classify_failure(detail, returncode=process.returncode, fallback="The file could not be read.")
    return bytes(data[:max_bytes])


def restore_snapshot(
    repo: str,
    password: str,
    snapshot_id: str,
    include_path: str,
    staging_target: str,
    *,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> ResticRunResult:
    """Restores only into the folder created by the staging service."""

    return run_restic(
        build_restore_args(repo, snapshot_id, include_path, staging_target), password,
        cancel_event=cancel_event, progress=progress, parse_progress=True,
    )


def _classify_failure(detail: str, *, returncode: int | None, fallback: str) -> ResticError:
    text = (detail or "").strip()
    lower = text.casefold()
    # The needles also contain German Windows messages: on a German Windows restic
    # passes through localised system errors.
    classifications = [
        (("wrong password", "no key found", "password is incorrect"), "password", "The repository password is wrong or does not belong to this repository.", "Enter the password again and only save it after a successful load."),
        (("already locked", "repository is locked", "unable to create lock"), "locked", "The repository is locked.", "Wait for running restic jobs. Only remove locks with `restic unlock` after checking."),
        (("no space left", "disk full", "not enough space", "nicht genügend speicher"), "space", "There is not enough free space on the disk.", "Free up space or choose a different staging/target folder."),
        (("access is denied", "permission denied", "zugriff verweigert"), "permission", "Access was denied.", "Check the Windows permissions and the NAS login for the chosen path."),
        (("network name", "network path", "device is not ready", "not reachable", "nicht erreichbar", "system cannot find the path", "pfad wurde nicht gefunden"), "network", "The network drive or repository is not reachable.", "Check the NAS, VPN/network and the Windows drive mapping, then try again."),
        (("no such file", "cannot find the file", "system cannot find the file"), "missing", "A required file or `restic.exe` was not found.", "Check `bin\\restic.exe`, the repository path and the snapshot, then reload."),
    ]
    for needles, kind, message, action in classifications:
        if any(needle in lower for needle in needles):
            return ResticError(message, kind=kind, detail=text, action=action, returncode=returncode)
    if returncode is None and ("winerror 2" in lower or "errno 2" in lower):
        return ResticError(
            "`restic.exe` was not found.", kind="executable", detail=text,
            action="Place the matching Windows build at `bin\\restic.exe`.",
        )
    return ResticError(
        fallback, kind="restic", detail=text,
        action="Check the repository, the network and free disk space, then try again.",
        returncode=returncode,
    )
