"""Kleine Tk-kompatible Worker-Verwaltung für exklusive lange Operationen."""

from __future__ import annotations

import threading
from typing import Callable


class TaskController:
    def __init__(self, tk_owner):
        self.owner = tk_owner
        self.cancel_event: threading.Event | None = None
        self.thread: threading.Thread | None = None
        self.name = ""

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(
        self,
        name: str,
        operation: Callable[[threading.Event, Callable[[float | None, str], None]], object],
        on_success: Callable[[object], None],
        on_error: Callable[[Exception], None],
        on_progress: Callable[[float | None, str], None],
        on_finished: Callable[[], None],
    ) -> bool:
        if self.busy:
            return False
        cancel_event = threading.Event()
        self.cancel_event = cancel_event
        self.name = name

        def progress(value: float | None, message: str):
            self.owner.after(0, lambda: on_progress(value, message))

        def worker():
            try:
                result = operation(cancel_event, progress)
            except Exception as exc:
                def finish_error(error=exc):
                    self._clear()
                    on_error(error)
                    on_finished()
                self.owner.after(0, finish_error)
            else:
                def finish_success(value=result):
                    self._clear()
                    on_success(value)
                    on_finished()
                self.owner.after(0, finish_success)

        self.thread = threading.Thread(target=worker, name=f"Orpheus-{name}", daemon=True)
        self.thread.start()
        return True

    def cancel(self):
        if self.cancel_event is not None:
            self.cancel_event.set()

    def _clear(self):
        self.thread = None
        self.cancel_event = None
        self.name = ""
