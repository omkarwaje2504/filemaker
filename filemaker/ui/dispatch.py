"""Run callbacks from worker threads on the Tk main thread.

Tkinter is not thread-safe, so background work (preview rendering,
production) never touches widgets directly; it hands callables to
`dispatch(fn, *args)`, which the main loop drains every few milliseconds.
"""
import queue


class Dispatcher:
    POLL_MS = 30

    def __init__(self, root):
        self._root = root
        self._queue = queue.Queue()
        self._root.after(self.POLL_MS, self._drain)

    def __call__(self, fn, *args):
        self._queue.put((fn, args))

    def _drain(self):
        try:
            while True:
                fn, args = self._queue.get_nowait()
                try:
                    fn(*args)
                except Exception as e:  # never let one callback kill the pump
                    print(f"[dispatch] {fn!r} failed: {e}")
        except queue.Empty:
            pass
        try:
            self._root.after(self.POLL_MS, self._drain)
        except Exception:
            pass  # window closed
