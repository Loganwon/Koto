"""The file drawer grows the app leftward, preserving the chat width."""

import threading


class FileDrawer:
    width = 224

    def __init__(self):
        self.open = False
        self._lock = threading.Lock()

    def set_open(self, window, expanded):
        import webview
        from webview.window import FixPoint

        with self._lock:
            if not window or self.open == expanded:
                return {"open": expanded, "width": self.width}
            if expanded:
                window.restore()
            width = window.width + (self.width if expanded else -self.width)
            window.resize(
                max(350, width), window.height, FixPoint.NORTH | FixPoint.EAST
            )
            # Keep an outward drawer on a monitor when the app is near its edge.
            if expanded:
                for screen in webview.screens:
                    if (
                        screen.y <= window.y < screen.y + screen.height
                        and window.x < screen.x < window.x + window.width
                    ):
                        window.move(screen.x, window.y)
                        break
            self.open = expanded
            return {"open": expanded, "width": self.width}
