"""Shared clean-up for Tk roots created by tests (P2-07).

Why this exists (seen in the Windows validation log):
- ``invalid command name "<id>poll"`` / ``"<id>quit"`` / ``"<id>warn_slow"``:
  ``after`` callbacks belong to the Tcl event queue of the *thread*, not to
  the window. When a test destroys its root while callbacks are pending, the
  next test that runs the event loop fires them and Tcl no longer knows the
  Python command. Cancelling every pending ``after`` before ``destroy()``
  removes them from the queue.
- ``Variable.__del__ ... main thread is not in main loop`` and ``Tcl
  interpreter is leaked``: Tk widgets and variables live in reference
  cycles, so they are freed by the garbage collector, which may run inside
  any thread. Collecting on the main thread right after the test, with the
  test's own references dropped and its worker threads finished, keeps the
  interpreter's end on the thread that created it.

Only test code uses this module. It never touches files, disks or the app's
behaviour, and it imports without ``tkinter`` (Linux containers).
"""
import gc
import threading
import time

try:  # pragma: no cover - depends on the Python build
    import tkinter as _tk
except ImportError:  # pragma: no cover
    _tk = None

_TCL_ERRORS = (RuntimeError,) + ((_tk.TclError,) if _tk is not None else ())
WORKER_JOIN_SECONDS = 1.0


def cancel_pending_afters(root):
    """Cancel every pending ``after``/``after idle`` of the root's interpreter.

    Works on a root that was already destroyed (the Tcl interpreter is still
    alive until garbage collection). Returns how many callbacks were cancelled.
    """
    try:
        pending = root.tk.splitlist(root.tk.call('after', 'info'))
    except Exception:  # noqa: BLE001 - clean-up must never fail a test
        return 0
    cancelled = 0
    for after_id in pending:
        # Plain Tcl ``after cancel`` only: ``root.after_cancel`` also runs
        # ``deletecommand``, which can raise (AttributeError/TclError) on a
        # destroyed root and could delete commands Tk itself scheduled.
        # The Python commands left behind are removed by ``destroy()``.
        try:
            root.tk.call('after', 'cancel', after_id)
        except Exception:  # noqa: BLE001
            continue
        cancelled += 1
    return cancelled


def close_tk_root(root):
    """Cancel pending callbacks, then destroy the root (tolerates a second call)."""
    if root is None:
        return 0
    cancelled = cancel_pending_afters(root)
    try:
        root.destroy()
    except _TCL_ERRORS:
        pass  # Already destroyed by the test itself.
    return cancelled


def _is_tk_object(value, root):
    if value is root:
        return True
    if _tk is None:
        return False
    return isinstance(value, (_tk.Misc, _tk.Variable))


def _join_new_threads(threads_before, budget):
    deadline = time.monotonic() + budget
    current = threading.current_thread()
    for thread in threading.enumerate():
        if thread is current or thread in threads_before:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            thread.join(remaining)
        except RuntimeError:
            continue  # e.g. a "dummy" thread created outside ``threading``.


def release_tk(testcase, holder, threads_before=(), join_seconds=WORKER_JOIN_SECONDS):
    """Close the tracked root and collect Tk objects on the calling thread.

    ``holder`` is a one-item list so this function owns the last reference it
    keeps; ``gc.collect()`` can then free the interpreter here.
    """
    root = holder.pop() if holder else None
    close_tk_root(root)
    # Worker threads started during the test may still hold Tk objects
    # (closures with StringVar etc.); let them end before collecting.
    _join_new_threads(set(threads_before), join_seconds)
    for name, value in list(vars(testcase).items()):
        if _is_tk_object(value, root):
            setattr(testcase, name, None)
    del root
    gc.collect()


def track_tk_root(testcase, root, join_seconds=WORKER_JOIN_SECONDS):
    """Register the root for safe clean-up at the end of the test. Returns it.

    Replaces ``addCleanup(root.destroy)`` (and ``addCleanup(gc.collect)``):
    the clean-up cancels pending ``after`` callbacks, destroys the root,
    waits briefly for threads the test started, drops the test's Tk
    attributes and runs ``gc.collect()`` on the main thread.
    """
    threads_before = tuple(threading.enumerate())
    testcase.addCleanup(release_tk, testcase, [root], threads_before, join_seconds)
    return root
