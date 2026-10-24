"""Small, borderless canvas controls that follow the app palette."""
import tkinter as tk


class SlimScrollbar(tk.Canvas):
    """Trackless rounded scrollbar with a generous, stable mouse target."""

    def __init__(self, parent, command, bg=None, **kwargs):
        super().__init__(parent, width=12, bg=bg or parent.cget("bg"),
                         highlightthickness=0, bd=0, takefocus=1, **kwargs)
        self.command = command
        self.first, self.last = 0.0, 1.0
        self.hover = self.dragging = False
        self.drag_offset = 0
        self.bind("<Configure>", self.draw)
        self.bind("<Enter>", self.enter)
        self.bind("<Leave>", self.leave)
        self.bind("<Button-1>", self.press)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<MouseWheel>", self.wheel)
        self.bind("<Up>", lambda e: self.command("scroll", -1, "units"))
        self.bind("<Down>", lambda e: self.command("scroll", 1, "units"))
        self.bind("<Prior>", lambda e: self.command("scroll", -1, "pages"))
        self.bind("<Next>", lambda e: self.command("scroll", 1, "pages"))
        self.bind("<Home>", lambda e: self.command("moveto", 0))
        self.bind("<End>", lambda e: self.command("moveto", 1))

    def set(self, first, last):
        self.first = max(0.0, min(1.0, float(first)))
        self.last = max(self.first, min(1.0, float(last)))
        self.draw()

    def geometry_values(self):
        inset = 7
        available = max(1, self.winfo_height()-2*inset)
        span = self.last-self.first
        thumb = min(available, max(32, min(140, available*span)))
        travel = max(1, available-thumb)
        top = inset+travel*self.first/max(0.000001, 1-span)
        return top, thumb, travel, span, inset

    def draw(self, event=None):
        self.delete("all")
        if self.last-self.first >= 0.9999:
            return
        top, thumb, _, _, _ = self.geometry_values()
        width = 7 if self.hover or self.dragging else 4
        color = "#668774" if self.dragging else "#8ba393" if self.hover else "#c3cfc4"
        x = max(12, self.winfo_width())/2
        self.create_line(x, top+width/2, x, top+thumb-width/2,
                         width=width, fill=color, capstyle="round")

    def enter(self, event=None):
        self.hover = True
        self.draw()

    def leave(self, event=None):
        self.hover = False
        self.draw()

    def press(self, event):
        if self.last-self.first >= 0.9999:
            return
        self.focus_set()
        top, thumb, _, _, _ = self.geometry_values()
        self.drag_offset = event.y-top if top <= event.y <= top+thumb else thumb/2
        self.dragging = True
        self.drag(event)

    def drag(self, event):
        if not self.dragging:
            return
        _, _, travel, span, inset = self.geometry_values()
        position = max(0, min(1, (event.y-self.drag_offset-inset)/travel))
        self.command("moveto", position*(1-span))
        self.draw()

    def release(self, event=None):
        self.dragging = False
        self.draw()

    def wheel(self, event):
        self.command("scroll", -int(event.delta/120), "units")
        return "break"


class ProgressTrack(tk.Canvas):
    """A quiet 5px progress line without platform bevels or borders."""

    def __init__(self, parent, value=0, length=180, track="#dce6dc", fill="#24634c"):
        super().__init__(parent, width=length, height=6, bg=parent.cget("bg"),
                         bd=0, highlightthickness=0)
        self.value = max(0, min(100, value))
        self.track, self.fill = track, fill
        self.bind("<Configure>", self.draw)

    def draw(self, event=None):
        self.delete("all")
        width, y = self.winfo_width(), self.winfo_height()/2
        self.create_line(3, y, max(3, width-3), y, width=5, fill=self.track, capstyle="round")
        if self.value:
            self.create_line(3, y, max(3, 3+(width-6)*self.value/100), y,
                             width=5, fill=self.fill, capstyle="round")
