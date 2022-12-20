import time
import fcntl, struct, termios
from sys import stdout

from textual import events, log
from textual.widgets import Static

from fhost import app as fhost_app

class MpvWidget(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.mpv = None
        self.vo = fhost_app.config.get("MOD_PREVIEW_PROTO")

        if not self.vo in ["sixel", "kitty"]:
            self.update("⚠ Previews not enabled. \n\nSet MOD_PREVIEW_PROTO to 'sixel' or 'kitty' in config.py,\nwhichever is supported by your terminal.")
        else:
            try:
                import mpv
                self.mpv = mpv.MPV()
                self.mpv.profile = "sw-fast"
                self.mpv["vo"] = self.vo
                self.mpv[f"vo-{self.vo}-config-clear"] = False
                self.mpv[f"vo-{self.vo}-alt-screen"] = False
                self.mpv[f"vo-sixel-buffered"] = True
                self.mpv["audio"] = False
                self.mpv["loop-file"] = "inf"
                self.mpv["image-display-duration"] = 0.5 if self.vo == "sixel" else "inf"
            except Exception as e:
                self.mpv = None
                self.update(f"⚠ Previews require python-mpv with libmpv 0.36.0 or later \n\nError was:\n{type(e).__name__}: {e}")

    def start_mpv(self, f: str|None = None, pos: float|str|None = None) -> None:
        self.display = True
        self.screen._refresh_layout()

        if self.mpv:
            if self.content_region.x:
                r, c, w, h = struct.unpack('hhhh', fcntl.ioctl(0, termios.TIOCGWINSZ, '12345678'))
                width = int((w / c) * self.content_region.width)
                height = int((h / r) * (self.content_region.height + (1 if self.vo == "sixel" else 0)))
                self.mpv[f"vo-{self.vo}-left"] = self.content_region.x + 1
                self.mpv[f"vo-{self.vo}-top"] = self.content_region.y + 1
                self.mpv[f"vo-{self.vo}-rows"] = self.content_region.height + (1 if self.vo == "sixel" else 0)
                self.mpv[f"vo-{self.vo}-cols"] = self.content_region.width
                self.mpv[f"vo-{self.vo}-width"] = width
                self.mpv[f"vo-{self.vo}-height"] = height

                if pos != None:
                    self.mpv["start"] = pos

                if f:
                    self.mpv.loadfile(f)
                else:
                    self.mpv.playlist_play_index(0)

    def stop_mpv(self, wait: bool = False) -> None:
        if self.mpv:
            if not self.mpv.idle_active:
                self.mpv.stop(True)
                if wait:
                    time.sleep(0.1)
        self.clear_mpv()
        self.display = False

    def on_resize(self, size) -> None:
        if self.mpv:
            if not self.mpv.idle_active:
                t = self.mpv.time_pos
                self.stop_mpv()
                if t:
                    self.mpv["start"] = t
                self.start_mpv()

    def clear_mpv(self) -> None:
        if self.vo == "kitty":
            stdout.write("\033_Ga=d;\033\\")
            stdout.flush()

    def shutdown(self) -> None:
        if self.mpv:
            self.mpv.stop()
            del self.mpv
            if self.vo == "kitty":
                stdout.write("\033_Ga=d;\033\\\033[?25l")
                stdout.flush()
