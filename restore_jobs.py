"""Workers exchange plain Python data. They never call Tkinter."""
import queue
import threading


class Job:
    def __init__(self,work):
        self.cancelled=threading.Event()
        self.result=queue.Queue(maxsize=1)
        self.latest=None
        def progress(*value):self.latest=value
        def run():
            try:self.result.put(('done',work(self.cancelled,progress)))
            except Exception as exc:self.result.put(('cancelled' if isinstance(exc,InterruptedError) else 'error',str(exc)))
        self.thread=threading.Thread(target=run,daemon=True)
        self.thread.start()
    def poll(self):
        try:return self.result.get_nowait()
        except queue.Empty:return None
