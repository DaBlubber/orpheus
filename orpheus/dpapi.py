"""Windows DPAPI for secrets bound to the current user."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _input_blob(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _require_windows():
    if os.name != "nt" or not hasattr(ctypes, "windll"):
        raise OSError("Windows DPAPI is not available on this system.")


def _last_error(operation: str) -> OSError:
    code = ctypes.get_last_error()
    if not code and hasattr(ctypes, "windll"):
        code = ctypes.windll.kernel32.GetLastError()
    return OSError(code, f"{operation} failed")


def protect(plaintext: str) -> bytes:
    """Encrypts text for the current Windows user, without a UI prompt."""

    _require_windows()
    in_blob, in_buffer = _input_blob(plaintext.encode("utf-8"))
    out_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise _last_error("CryptProtectData")
    del in_buffer
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def unprotect(ciphertext: bytes) -> str:
    """Decrypts current DPAPI blobs and old ones migrated unchanged."""

    _require_windows()
    in_blob, in_buffer = _input_blob(ciphertext)
    out_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise _last_error("CryptUnprotectData")
    del in_buffer
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
