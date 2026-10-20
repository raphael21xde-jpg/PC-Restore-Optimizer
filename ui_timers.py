"""Tk callback ownership: cancel only callbacks scheduled by the closing widget.

Tk after callbacks are interpreter-wide. Destroying one window without
cancelling its outstanding callbacks can leave invalid Tcl command names.
This helper does not stop jobs or destroy widgets; it only owns timers.
"""
import tkinter as tk


class WindowTimers:
    def __init__(self, owner):
        self.owner = owner
        self.pending = set()
        self.closed = False
        owner.bind('<Destroy>', self._on_destroy, add='+')

    def _on_destroy(self, event):
        # Destroy also bubbles from descendants; only the owner closes us.
        if event.widget is self.owner:
            self.close()

    def after(self, delay_ms, callback, *args):
        if self.closed:
            return None
        try:
            if not self.owner.winfo_exists():
                self.close()
                return None
        except tk.TclError:
            self.close()
            return None

        token = [None]

        def run():
            self.pending.discard(token[0])
            if not self.closed:
                callback(*args)

        try:
            token[0] = self.owner.after(delay_ms, run)
        except tk.TclError:
            self.close()
            return None
        self.pending.add(token[0])
        return token[0]

    def cancel(self, token):
        if token is None:
            return
        if token not in self.pending:
            return
        self.pending.discard(token)
        try:
            self.owner.after_cancel(token)
        except tk.TclError:
            # It may have been removed by widget destruction.
            pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        for token in tuple(self.pending):
            self.cancel(token)
