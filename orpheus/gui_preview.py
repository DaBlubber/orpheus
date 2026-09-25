"""Tk controller mixin for the file and image preview."""

from __future__ import annotations

import io
import threading

from . import restic_client as rc
from .preview import decode_text, preview_kind
from .restore_service import format_bytes


class PreviewControllerMixin:
    def _on_file_select(self, _event=None):
        selected = self.view.file_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        path = self._iid_to_path.get(item_id)
        node = self._iid_to_node.get(item_id)
        if not path or node is None:
            return
        self._selected_include = path
        self.view.selected_path_var.set(path)
        self._preview_cancel.set()
        self._preview_cancel = threading.Event()
        self._preview_generation += 1
        generation = self._preview_generation
        if node.get("type") == "dir" or preview_kind(path) == "metadata":
            self._show_preview_meta(node)
            return
        kind = preview_kind(path)
        limit = 5 * 1024 * 1024 if kind == "image" else 65536
        self._show_preview_placeholder("Loading preview ...")
        self.view.status_var.set(f"Loading preview: {path}")
        repo, password, snapshot = self._current_repo, self._current_password, self._current_snapshot_id
        cancel_event = self._preview_cancel

        def worker():
            try:
                data = rc.dump_file(repo, password, snapshot, path, max_bytes=limit, cancel_event=cancel_event)
            except rc.OperationCancelled:
                return
            except Exception as exc:
                self.after(0, lambda error=exc: self._preview_error(error, generation))
                return
            self.after(0, lambda: self._display_preview(kind, data, limit, generation))

        threading.Thread(target=worker, name="Orpheus-preview", daemon=True).start()

    def _preview_error(self, error: Exception, generation: int):
        if generation != self._preview_generation:
            return
        message = error.user_message() if isinstance(error, rc.ResticError) else str(error)
        self._show_preview_placeholder(f"Preview not available\n\n{message}")
        self.view.status_var.set("The preview could not be loaded.")

    def _display_preview(self, kind: str, data: bytes, limit: int, generation: int):
        if generation != self._preview_generation:
            return
        if kind == "text":
            self._show_preview_text(decode_text(data), len(data) >= limit)
        else:
            self._show_preview_image(data, len(data) >= limit)
        self.view.status_var.set("Preview loaded.")

    def _hide_preview_widgets(self):
        for widget in (
            self.view.preview_text, self.view.preview_text_vscroll,
            self.view.preview_text_hscroll, self.view.preview_image_label,
            self.view.preview_info_label,
        ):
            widget.grid_forget()

    def _show_preview_placeholder(self, message: str):
        self._hide_preview_widgets()
        self.view.preview_info_label.configure(
            text=message, foreground=self.view.colors["hint"], image=""
        )
        self.view.preview_info_label.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _show_preview_text(self, content: str, truncated: bool):
        self._hide_preview_widgets()
        self.view.preview_text.configure(state="normal")
        self.view.preview_text.delete("1.0", "end")
        self.view.preview_text.insert("end", content)
        if truncated:
            self.view.preview_text.insert("end", "\n\n... (preview limited to 64 KB)")
        self.view.preview_text.configure(state="disabled")
        self.view.preview_text.grid(row=0, column=0, sticky="nsew")
        self.view.preview_text_vscroll.grid(row=0, column=1, sticky="ns")
        self.view.preview_text_hscroll.grid(row=1, column=0, sticky="ew")

    def _show_preview_image(self, data: bytes, truncated: bool):
        try:
            from PIL import Image, ImageTk
            image = Image.open(io.BytesIO(data))
            image.load()
            width = max(self.view.preview_frame.winfo_width() - 16, 200)
            height = max(self.view.preview_frame.winfo_height() - 16, 200)
            image.thumbnail((width, height), Image.LANCZOS)
            self._preview_image = ImageTk.PhotoImage(image)
        except ImportError:
            self._show_preview_placeholder("The image preview needs the optional Pillow package.\n`pip install Pillow`")
            return
        except Exception as exc:
            suffix = " The file is larger than the 5 MB preview limit." if truncated else ""
            self._show_preview_placeholder(f"The image preview could not be read.{suffix}\n\n{exc}")
            return
        self._hide_preview_widgets()
        self.view.preview_image_label.configure(image=self._preview_image)
        self.view.preview_image_label.grid(row=0, column=0, sticky="nsew")

    def _show_preview_meta(self, node: dict):
        self._show_preview_placeholder(
            "\n".join((
                f"Type: {node.get('type', '?')}",
                f"Size: {format_bytes(int(node.get('size') or 0))}",
                f"Modified: {str(node.get('mtime') or '')[:19].replace('T', ' ')}",
                f"Mode: {node.get('mode', '')}",
                "",
                "For this file type only the metadata view is used, on purpose.",
            ))
        )
