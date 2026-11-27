"""The live cartoon: a sprite loader and the speech window that delivers reminders.
The window is borderless, has no taskbar button, never takes focus, and is transparent via a colour key."""
from __future__ import annotations

import math
import random
import sys
import time
import tkinter as tk
from pathlib import Path

from . import core, winutil
from .theme import ACCENT, BORDER, FONT, INK, KEY, SOFT, make_button

if getattr(sys, "frozen", False):                      # running as a PyInstaller-built DesktopPet.exe
    ASSETS = Path(sys._MEIPASS) / "desktop_pet" / "assets"
else:
    ASSETS = Path(__file__).parent / "assets"
HEIGHTS = (115, 170)          # kitten height in pixels at 100% / 150%+ display scaling
FOOT_FRACTION = 0.0246        # transparent margin under the paws, as a fraction of the sprite image height


class Sprites:
    """Loads the pre-rendered pet frames (PNG) at a size that suits the display scaling."""

    COUNTS = {"idle": 4, "talk": 6, "happy": 6, "blink": 1}
    ROWS = ("idle", "talk", "happy", "blink")     # sprite-sheet layout, see tools/build_sprites.py
    COLS = 6

    def __init__(self, root: tk.Misc):
        self.scale = root.winfo_fpixels("1i") / 96.0
        self.speech_h = HEIGHTS[1 if self.scale >= 1.4 else 0]
        self._cache = {}
        self._sheets = {}

    def get(self, pet: str, anim: str, direction: str, index: int, height: int) -> tk.PhotoImage:
        index %= self.COUNTS[anim]
        key = (pet, anim, index, height)
        if key not in self._cache:
            sheet = self._sheets.get((pet, height))
            if sheet is None:
                sheet = self._sheets[(pet, height)] = tk.PhotoImage(file=str(ASSETS / f"{pet}_{height}.png"))
            cw, ch = sheet.width() // self.COLS, sheet.height() // len(self.ROWS)
            x0, y0 = index * cw, self.ROWS.index(anim) * ch
            frame = tk.PhotoImage(width=cw, height=ch)
            frame.tk.call(frame.name, "copy", sheet.name, "-from", x0, y0, x0 + cw, y0 + ch, "-to", 0, 0)
            self._cache[key] = frame
        return self._cache[key]


def _keyed_toplevel(root: tk.Misc) -> tk.Toplevel:
    win = tk.Toplevel(root)
    win.withdraw()
    win.overrideredirect(True)                  # no title bar and no taskbar button
    win.configure(bg=KEY)
    try:
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY)
    except tk.TclError:
        pass
    return win


# ----------------------------------------------------------------------------- speech window (the reminder)


def _rounded_points(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
            x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class SpeechWindow:
    """The pet appears (bottom-right, just above the taskbar), talks in a speech bubble and waits for your answer.
    Appears once, never takes focus, fades out of your way if ignored. A break countdown can run inside the bubble."""

    TIMEOUT_MS = 60_000

    def __init__(self, app, reminder: core.Reminder, test: bool = False):
        self.app = app
        self.reminder = reminder
        self.test = test
        self.sp: Sprites = app.sprites
        self.s = self.sp.scale
        self.win = _keyed_toplevel(app.root)
        self._closed = False
        self._jobs = {}
        self._anim = "talk"
        self._frame = 0
        self._paused = False
        self._remaining = float(reminder.break_seconds)
        self._last = 0.0
        self._base_bottom = None
        self._clock_item = None

        s = self.s
        self.pad = int(14 * s)
        self.bw = int(270 * s)
        first = self.sp.get(reminder.pet, "idle", "r", 0, self.sp.speech_h)
        self.iw, self.ih = first.width(), first.height()
        self.W = max(self.bw + int(10 * s), self.iw)

        self.canvas = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0, width=self.W, height=self.ih + 100)
        self.canvas.pack()
        wrap = self.bw - 2 * self.pad
        self.bubble = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, fill="white", outline=BORDER, width=2)
        self.pointer = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, fill="white", outline=BORDER, width=2)
        self.t_title = self.canvas.create_text(0, 0, anchor="nw", width=wrap, fill=INK, font=(FONT, 12, "bold"), text=reminder.name)
        self.full_message = reminder.message or "Time for your reminder."
        self.t_msg = self.canvas.create_text(0, 0, anchor="nw", width=wrap, fill=SOFT, font=(FONT, 10), text=self.full_message)
        self.btn_frame = tk.Frame(self.canvas, bg="white")
        self.w_buttons = self.canvas.create_window(0, 0, anchor="nw", window=self.btn_frame)
        self.pet = self.canvas.create_image(0, 0, anchor="nw", image=first)
        self.canvas.tag_raise(self.pet)

        self._msg_height = self._height(self.t_msg)
        self._build_prompt_buttons()
        self._layout()
        self.canvas.itemconfigure(self.t_msg, text="")
        self._typed = 0
        self.win.deiconify()
        if reminder.sound:
            winutil.play_chime("reminder")
        self._jobs["type"] = self.win.after(250, self._type)
        self._jobs["anim"] = self.win.after(130, self._animate)
        self._jobs["timeout"] = self.win.after(self.TIMEOUT_MS, lambda: self.app.on_skip(self))

    # ---- layout
    def _height(self, item) -> int:
        box = self.canvas.bbox(item)
        return (box[3] - box[1]) if box else 0

    def _build_prompt_buttons(self) -> None:
        for child in self.btn_frame.winfo_children():
            child.destroy()
        r = self.reminder
        primary = "Start break" if r.break_seconds > 0 else "Done"
        make_button(self.btn_frame, primary, self._primary, primary=True, small=True).pack(side="left")
        make_button(self.btn_frame, f"Snooze {r.snooze_min} min", lambda: self.app.on_snooze(self), small=True).pack(side="left", padx=5)
        make_button(self.btn_frame, "Not now", lambda: self.app.on_skip(self), small=True).pack(side="left")

    def _layout(self) -> None:
        c, s, pad = self.canvas, self.s, self.pad
        x0 = self.W - self.bw
        y = pad
        c.coords(self.t_title, x0 + pad, y)
        y += self._height(self.t_title) + int(5 * s)
        c.coords(self.t_msg, x0 + pad, y)
        y += self._msg_height + int(6 * s)
        if self._clock_item is not None:
            c.coords(self._clock_item, x0 + pad, y)
            y += self._height(self._clock_item) + int(6 * s)
        c.coords(self.w_buttons, x0 + pad, y)
        self.btn_frame.update_idletasks()
        y += self.btn_frame.winfo_reqheight() + pad
        bubble_h = y
        c.coords(self.bubble, *_rounded_points(x0, 2, x0 + self.bw, bubble_h, int(16 * s)))
        cat_x = self.W - self.iw // 2
        px = min(max(cat_x, x0 + int(40 * s)), x0 + self.bw - int(40 * s))
        c.coords(self.pointer, px - int(14 * s), bubble_h - 1, px + int(14 * s), bubble_h - 1, px + int(4 * s), bubble_h + int(18 * s))
        sprite_y = bubble_h + int(10 * s)
        c.coords(self.pet, self.W - self.iw, sprite_y)
        total_h = sprite_y + self.ih
        c.configure(height=total_h)
        self._place(total_h)

    def _place(self, total_h: int) -> None:
        left, top, right, bottom = winutil.work_area(self.win.winfo_screenwidth(), self.win.winfo_screenheight())
        if self._base_bottom is None:
            overlap = round(self.ih * FOOT_FRACTION) + (2 if bottom < self.win.winfo_screenheight() else 0)
            self._base_bottom = bottom + overlap
        x = right - self.W - int(12 * self.s)
        x = int(min(max(x, left), right - self.W))
        self.win.geometry(f"{self.W}x{total_h}+{x}+{int(self._base_bottom - total_h)}")

    # ---- animation
    def _type(self) -> None:
        self._jobs.pop("type", None)
        if self._closed:
            return
        step = max(1, len(self.full_message) // 55)
        self._typed = min(len(self.full_message), self._typed + step)
        self.canvas.itemconfigure(self.t_msg, text=self.full_message[: self._typed])
        if self._typed < len(self.full_message):
            self._jobs["type"] = self.win.after(28, self._type)
        elif self._anim == "talk":
            self._anim = "idle"

    def _animate(self) -> None:
        self._jobs.pop("anim", None)
        if self._closed:
            return
        self._frame += 1
        anim = self._anim
        delay = 130
        if anim == "idle":
            delay = 280
            if random.random() < 0.07:            # a quick blink
                anim, self._frame, delay = "blink", 0, 150
        elif anim == "blink":
            anim = "idle"
        image = self.sp.get(self.reminder.pet, anim, "r", self._frame, self.sp.speech_h)
        self.canvas.itemconfigure(self.pet, image=image)
        self.canvas.image = image
        if self._anim == "blink":
            self._anim = "idle"
        self._jobs["anim"] = self.win.after(delay, self._animate)

    # ---- actions
    def _primary(self) -> None:
        if self.reminder.break_seconds > 0:
            self._start_countdown()
        else:
            self.app.on_done(self)

    def _start_countdown(self) -> None:
        self._cancel("timeout")
        self.full_message = "Take your time. Breathe, and let your shoulders drop."
        self.canvas.itemconfigure(self.t_msg, text=self.full_message)
        self._msg_height = self._height(self.t_msg)
        self._clock_item = self.canvas.create_text(0, 0, anchor="nw", fill=INK, font=(FONT, 26, "bold"), text=self._fmt(self._remaining))
        for child in self.btn_frame.winfo_children():
            child.destroy()
        self.pause_button = make_button(self.btn_frame, "Pause", self._toggle_pause, primary=True, small=True)
        self.pause_button.pack(side="left")
        make_button(self.btn_frame, "End break", lambda: self.app.on_done(self), small=True).pack(side="left", padx=5)
        self._anim = "idle"
        self._layout()
        self._last = time.monotonic()
        self._jobs["count"] = self.win.after(200, self._count)

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = max(0, int(seconds + 0.999))
        return f"{s // 60:02d}:{s % 60:02d}"

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.configure(text="Resume" if self._paused else "Pause")
        self._last = time.monotonic()

    def _count(self) -> None:
        self._jobs.pop("count", None)
        if self._closed:
            return
        now = time.monotonic()
        if not self._paused:
            self._remaining -= now - self._last
        self._last = now
        self.canvas.itemconfigure(self._clock_item, text=self._fmt(self._remaining))
        if self._remaining <= 0:
            self._finish()
        else:
            self._jobs["count"] = self.win.after(200, self._count)

    def _finish(self) -> None:
        self._anim = "happy"
        self.canvas.itemconfigure(self.t_title, text="All done!")
        self.full_message = "Lovely. Back to it whenever you're ready."
        self.canvas.itemconfigure(self.t_msg, text=self.full_message)
        self._msg_height = self._height(self.t_msg)
        self.canvas.itemconfigure(self._clock_item, text="00:00")
        for child in self.btn_frame.winfo_children():
            child.destroy()
        make_button(self.btn_frame, "Done", lambda: self.app.on_done(self), primary=True, small=True).pack(side="left")
        self._layout()
        if self.reminder.sound:
            winutil.play_chime("finished")

    # ---- closing
    def _cancel(self, name: str) -> None:
        job = self._jobs.pop(name, None)
        if job is not None:
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for name in list(self._jobs):
            self._cancel(name)
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ----------------------------------------------------------------------------- message pop-up (replaces plain message boxes)


class MessageWindow:
    """A pet says something and waits for a button: the cartoon replacement for Windows message boxes.
    Modal: run() returns the index of the pressed button (None if closed with Escape on a one-button message)."""

    def __init__(self, app, text: str, title: str = "Desktop Pet", buttons=("OK",), pet: str = "mochi", anchor=None):
        self.app = app
        self.sp: Sprites = app.sprites
        self.s = self.sp.scale
        self.result = None
        self._closed = False
        self._job = None
        self._prev_grab = None
        self._frame = 0
        s, pad = self.s, int(14 * self.s)
        self.pet_id = pet if pet in core.PETS else next(iter(core.PETS))
        self.win = _keyed_toplevel(app.root)
        first = self.sp.get(self.pet_id, "idle", "r", 0, self.sp.speech_h)
        self.iw, self.ih = first.width(), first.height()
        bw = int(270 * s)
        W = max(bw + int(10 * s), self.iw)
        self.W = W
        c = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0, width=W, height=self.ih + 140)
        c.pack()
        self.canvas = c
        x0 = W - bw
        bubble = c.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, fill="white", outline=BORDER, width=2)
        pointer = c.create_polygon(0, 0, 0, 0, 0, 0, fill="white", outline=BORDER, width=2)
        t_title = c.create_text(x0 + pad, pad, anchor="nw", width=bw - 2 * pad, fill=INK, font=(FONT, 12, "bold"), text=title)
        y = pad + self._height(t_title) + int(5 * s)
        t_msg = c.create_text(x0 + pad, y, anchor="nw", width=bw - 2 * pad, fill=INK, font=(FONT, 10), text=text)
        y += self._height(t_msg) + int(10 * s)
        frame = tk.Frame(c, bg="white")
        for i, label in enumerate(buttons):
            make_button(frame, label, lambda i=i: self._pick(i), primary=(i == 0), small=True).pack(side="left", padx=(0, 6))
        c.create_window(x0 + pad, y, anchor="nw", window=frame)
        frame.update_idletasks()
        y += frame.winfo_reqheight() + pad
        c.coords(bubble, *_rounded_points(x0, 2, x0 + bw, y, int(16 * s)))
        px = min(max(W - self.iw // 2, x0 + int(40 * s)), x0 + bw - int(40 * s))
        c.coords(pointer, px - int(14 * s), y - 1, px + int(14 * s), y - 1, px + int(4 * s), y + int(18 * s))
        sprite_y = y + int(10 * s)
        self.pet = c.create_image(W - self.iw, sprite_y, anchor="nw", image=first)
        total_h = sprite_y + self.ih
        c.configure(height=total_h)
        self._place(total_h, anchor)
        self.win.bind("<Return>", lambda e: self._pick(0))
        self.win.bind("<Escape>", lambda e: self._pick(len(buttons) - 1))

    def _height(self, item) -> int:
        box = self.canvas.bbox(item)
        return (box[3] - box[1]) if box else 0

    def _place(self, total_h: int, anchor) -> None:
        left, top, right, bottom = winutil.work_area(self.win.winfo_screenwidth(), self.win.winfo_screenheight())
        try:
            near = anchor is not None and anchor.winfo_viewable()
        except tk.TclError:
            near = False
        if near:
            x = anchor.winfo_rootx() + anchor.winfo_width() // 2 - self.W // 2
            y = anchor.winfo_rooty() + anchor.winfo_height() - int(8 * self.s) - total_h
        else:
            x = right - self.W - int(12 * self.s)
            y = bottom + round(self.ih * FOOT_FRACTION) - total_h
        x = int(min(max(x, left), right - self.W))
        y = int(max(top, y))
        self.win.geometry(f"{self.W}x{total_h}+{x}+{y}")

    def _animate(self) -> None:
        self._job = None
        if self._closed:
            return
        self._frame += 1
        anim = "blink" if random.random() < 0.08 else "idle"
        image = self.sp.get(self.pet_id, anim, "r", self._frame, self.sp.speech_h)
        self.canvas.itemconfigure(self.pet, image=image)
        self.canvas.image = image
        self._job = self.win.after(280 if anim == "idle" else 150, self._animate)

    def _pick(self, index: int) -> None:
        if self.result is None:
            self.result = index
        self.close()

    def run(self):
        try:
            self._prev_grab = self.app.root.grab_current()
        except tk.TclError:
            self._prev_grab = None
        self.win.deiconify()
        self.win.lift()
        try:
            self.win.grab_set()
            self.win.focus_force()
        except tk.TclError:
            pass
        self._job = self.win.after(280, self._animate)
        self.win.wait_window(self.win)
        return self.result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._job is not None:
            try:
                self.win.after_cancel(self._job)
            except tk.TclError:
                pass
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self._prev_grab is not None:                 # give the grab back to the dialog underneath
            try:
                self._prev_grab.grab_set()
            except tk.TclError:
                pass
