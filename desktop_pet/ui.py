"""Windows, tray handling and the app controller. Offline: nothing here talks to a network."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk

from . import core, winutil
from .actors import ASSETS, MessageWindow, SpeechWindow, Sprites
from .theme import ACCENT, ACCENT_ACTIVE, CREAM, FONT, INK, SOFT, make_button
from .tray import Tray

SCRIPT = Path(__file__).resolve().parent.parent / "DesktopPet.pyw"


def log_error(message: str) -> None:
    """Local error log only (%AppData%\\DesktopPet\\log.txt, capped)."""
    try:
        path = core.data_dir() / "log.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 128 * 1024:
            path.unlink()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def describe_due(due, now: datetime) -> str:
    if due is None:
        return ""
    secs = (due - now).total_seconds()
    if secs < 60:
        return "any moment"
    if secs < 3600:
        return f"in {int(secs // 60) + 1} min"
    if due.date() == now.date():
        return f"today {due:%H:%M}"
    if due.date() == (now + timedelta(days=1)).date():
        return f"tomorrow {due:%H:%M}"
    return f"{due:%a %H:%M}"


class ReminderDialog(tk.Toplevel):
    """Edit one reminder: name, message, companion, schedule, break length, snooze, active hours."""

    def __init__(self, app, reminder: core.Reminder, title: str):
        parent = app.manager if app.manager is not None else app.root
        super().__init__(parent)
        self.app = app
        self.source = reminder
        self.result = None
        self.title(title)
        self.configure(bg=CREAM)
        self.transient(parent)
        self.resizable(False, False)

        self.v_name = tk.StringVar(value=reminder.name)
        self.v_message = tk.StringVar(value=reminder.message)
        self._pet_labels = [f"{v['name']} ({v['kind']})" for v in core.PETS.values()]
        self._pet_ids = list(core.PETS)
        self.v_pet = tk.StringVar(value=self._pet_labels[self._pet_ids.index(reminder.pet) if reminder.pet in self._pet_ids else 0])
        self.v_kind = tk.StringVar(value=reminder.kind)
        self.v_interval = tk.StringVar(value=str(reminder.interval_min))
        self.v_times = tk.StringVar(value=", ".join(reminder.times))
        self.v_break = tk.StringVar(value=str(reminder.break_seconds))
        self.v_snooze = tk.StringVar(value=str(reminder.snooze_min))
        self.v_from = tk.StringVar(value=reminder.active_from)
        self.v_to = tk.StringVar(value=reminder.active_to)
        self.v_sound = tk.BooleanVar(value=reminder.sound)
        self.v_enabled = tk.BooleanVar(value=reminder.enabled)

        f = tk.Frame(self, bg=CREAM)
        f.pack(padx=18, pady=16)

        def label(row, text):
            tk.Label(f, text=text, bg=CREAM, fg=INK, font=(FONT, 10), anchor="w").grid(row=row, column=0, sticky="w", pady=5, padx=(0, 12))

        label(0, "Name")
        ttk.Entry(f, textvariable=self.v_name, width=42).grid(row=0, column=1, columnspan=3, sticky="we")
        label(1, "Message")
        ttk.Entry(f, textvariable=self.v_message, width=42).grid(row=1, column=1, columnspan=3, sticky="we")

        label(2, "Companion")
        ttk.Combobox(f, textvariable=self.v_pet, values=self._pet_labels, state="readonly", width=28).grid(row=2, column=1, columnspan=3, sticky="w")

        label(3, "Remind me")
        row3 = tk.Frame(f, bg=CREAM)
        row3.grid(row=3, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(row3, text="every", variable=self.v_kind, value="interval").pack(side="left")
        ttk.Spinbox(row3, from_=1, to=1440, textvariable=self.v_interval, width=6).pack(side="left", padx=6)
        tk.Label(row3, text="minutes", bg=CREAM, fg=INK, font=(FONT, 10)).pack(side="left")
        row4 = tk.Frame(f, bg=CREAM)
        row4.grid(row=4, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(row4, text="at", variable=self.v_kind, value="times").pack(side="left")
        ttk.Entry(row4, textvariable=self.v_times, width=28).pack(side="left", padx=6)
        tk.Label(row4, text="e.g. 09:00, 13:30", bg=CREAM, fg=SOFT, font=(FONT, 9)).pack(side="left")

        label(5, "Break countdown")
        row5 = tk.Frame(f, bg=CREAM)
        row5.grid(row=5, column=1, columnspan=3, sticky="w")
        ttk.Spinbox(row5, from_=0, to=3600, textvariable=self.v_break, width=6).pack(side="left")
        tk.Label(row5, text="seconds  (0 = just a reminder; 20 = the 20-20-20 eye exercise)", bg=CREAM, fg=SOFT,
                 font=(FONT, 9)).pack(side="left", padx=6)

        label(6, "Snooze for")
        row6 = tk.Frame(f, bg=CREAM)
        row6.grid(row=6, column=1, columnspan=3, sticky="w")
        ttk.Spinbox(row6, from_=1, to=240, textvariable=self.v_snooze, width=6).pack(side="left")
        tk.Label(row6, text="minutes", bg=CREAM, fg=INK, font=(FONT, 10)).pack(side="left", padx=6)

        label(7, "Only between")
        row7 = tk.Frame(f, bg=CREAM)
        row7.grid(row=7, column=1, columnspan=3, sticky="w")
        ttk.Entry(row7, textvariable=self.v_from, width=7).pack(side="left")
        tk.Label(row7, text="and", bg=CREAM, fg=INK, font=(FONT, 10)).pack(side="left", padx=6)
        ttk.Entry(row7, textvariable=self.v_to, width=7).pack(side="left")

        opts = tk.Frame(f, bg=CREAM)
        opts.grid(row=8, column=1, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(opts, text="Play a soft chime", variable=self.v_sound).pack(side="left")
        ttk.Checkbutton(opts, text="Turned on", variable=self.v_enabled).pack(side="left", padx=16)

        buttons = tk.Frame(f, bg=CREAM)
        buttons.grid(row=9, column=0, columnspan=4, sticky="e", pady=(16, 0))
        make_button(buttons, "Cancel", self.destroy).pack(side="right")
        make_button(buttons, "Save", self._save, primary=True).pack(side="right", padx=8)

        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 30}+{parent.winfo_rooty() + 30}")
        self.deiconify()
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window(self)

    def _save(self) -> None:
        try:
            name = self.v_name.get().strip()
            if not name:
                raise ValueError("Please give the reminder a name.")
            interval = self._int(self.v_interval.get(), "Minutes", 1, 1440)
            brk = self._int(self.v_break.get(), "Break countdown", 0, 3600)
            snooze = self._int(self.v_snooze.get(), "Snooze", 1, 240)
            times = []
            if self.v_kind.get() == "times":
                for token in self.v_times.get().replace(";", ",").replace(" ", ",").split(","):
                    token = token.strip()
                    if not token:
                        continue
                    if not core.parse_hhmm(token):
                        raise ValueError(f"'{token}' is not a time. Use 24-hour HH:MM, like 09:00 or 13:30.")
                    times.append(token)
                if not times:
                    raise ValueError("Enter at least one time, like 09:00.")
            for text in (self.v_from.get(), self.v_to.get()):
                if not core.parse_hhmm(text):
                    raise ValueError("'Only between' needs times like 09:00 and 18:00.")
        except ValueError as ex:
            self.app.inform(str(ex), parent=self, pet=self._pet_ids[self._pet_labels.index(self.v_pet.get())])
            return

        self.result = core.Reminder(
            id=self.source.id, name=name, message=self.v_message.get(), pet=self._pet_ids[self._pet_labels.index(self.v_pet.get())],
            kind=self.v_kind.get(), interval_min=interval, times=times, break_seconds=brk, snooze_min=snooze,
            sound=self.v_sound.get(), active_from=self.v_from.get(), active_to=self.v_to.get(),
            enabled=self.v_enabled.get(),
        ).normalized()
        self.destroy()

    @staticmethod
    def _int(text: str, what: str, lo: int, hi: int) -> int:
        try:
            value = int(str(text).strip())
        except ValueError:
            raise ValueError(f"{what} must be a whole number.")
        if not lo <= value <= hi:
            raise ValueError(f"{what} must be between {lo} and {hi}.")
        return value


# ----------------------------------------------------------------------------- the app


class App:
    """Runs in the background: a tray icon, the cartoon, and a small settings window you open when you want it."""

    def __init__(self, minimized: bool = False):
        winutil.enable_dpi_awareness()
        winutil.set_app_id()

        self.root = tk.Tk()
        self.root.withdraw()                       # the hidden root means no window and no taskbar button
        self.root.title("Desktop Pet")
        try:
            self.root.iconbitmap(default=str(ASSETS / "app.ico"))
        except tk.TclError:
            pass
        self.sprites = Sprites(self.root)
        self.scale = self.sprites.scale

        self.store = core.Store()
        self.reminders, self.settings = self.store.load()
        now = datetime.now()
        self.sched = core.Scheduler(now)
        self.sched.set_reminders(self.reminders, now)
        self.sched.paused = self.settings.paused

        self.popup = None
        self.queue = []
        self.manager = None
        self.tree = None
        self._ticks = 0

        self.tray = Tray(str(ASSETS / "app.ico"))
        self.tray_ok = self.tray.start()
        self._sync_tray()

        if self.settings.start_with_windows:
            winutil.set_startup(True, str(SCRIPT))
        if self.store.first_run:
            self._save()

        self.root.after(1000, self._tick)
        self.root.after(200, self._poll_tray)
        self.root.after(15000, self._refresh_loop)
        if self.store.first_run or not self.tray_ok or not minimized:
            self.show_manager()

    def run(self) -> None:
        self.root.mainloop()

    # ---- tray
    def _sync_tray(self) -> None:
        self.tray.state["paused"] = self.settings.paused

    def _poll_tray(self) -> None:
        try:
            while True:
                event = self.tray.events.get_nowait()
                if event == "open":
                    self.show_manager()
                elif event == "pause":
                    self.set_paused(not self.settings.paused)
                elif event == "quit":
                    self.quit()
                    return
        except Exception:
            pass
        self.root.after(200, self._poll_tray)

    def set_paused(self, paused: bool) -> None:
        self.settings.paused = paused
        self.sched.set_paused(paused, datetime.now())
        if hasattr(self, "v_paused"):
            self.v_paused.set(paused)
        self._sync_tray()
        self._save()
        self.refresh()

    # ---- the settings window
    def show_manager(self) -> None:
        if self.manager is None:
            self._build_manager()
        self.manager.deiconify()
        self.manager.lift()
        self.refresh()

    def hide_manager(self) -> None:
        if self.manager is not None:
            if self.tray_ok:
                self.manager.withdraw()
            else:
                self.manager.iconify()      # no tray icon available: keep a way back

    def _build_manager(self) -> None:
        s = self.scale
        win = tk.Toplevel(self.root)
        self.manager = win
        win.title("Desktop Pet")
        win.configure(bg=CREAM)
        win.geometry(f"{int(500 * s)}x{int(340 * s)}")
        win.minsize(int(440 * s), int(300 * s))
        try:
            win.iconbitmap(default=str(ASSETS / "app.ico"))
            if self.tray_ok:
                win.attributes("-toolwindow", True)     # no taskbar button; reach it from the tray icon
        except tk.TclError:
            pass
        win.protocol("WM_DELETE_WINDOW", self.hide_manager)

        tk.Label(win, text="Reminders", font=(FONT, 13, "bold"), bg=CREAM, fg=INK).pack(anchor="w", padx=14, pady=(10, 4))

        style = ttk.Style()
        style.configure("Treeview", rowheight=int(22 * s), font=(FONT, 9))
        style.configure("Treeview.Heading", font=(FONT, 9, "bold"))
        mid = tk.Frame(win, bg=CREAM)
        mid.pack(fill="both", expand=True, padx=14)
        self.tree = ttk.Treeview(mid, columns=("on", "name", "when", "next"), show="headings", selectmode="browse")
        for col, text, width in (("on", "On", 36), ("name", "Reminder", 140), ("when", "When", 140), ("next", "Next", 100)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=int(width * s), anchor="center" if col == "on" else "w")
        self.tree.pack(side="left", fill="both", expand=True)
        bar_y = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        bar_y.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=bar_y.set)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.tree.bind("<Button-1>", self._on_tree_click)

        bar = tk.Frame(win, bg=CREAM)
        bar.pack(fill="x", padx=14, pady=(8, 2))
        add = tk.Menubutton(bar, text="Add \u25be", relief="flat", bd=0, cursor="hand2", font=(FONT, 9, "bold"),
                            bg=ACCENT, fg="white", activebackground=ACCENT_ACTIVE, activeforeground="white", padx=10, pady=4)
        menu = tk.Menu(add, tearoff=0)
        for key in core.TEMPLATES:
            menu.add_command(label=key, command=lambda k=key: self.add_from_template(k))
        add.configure(menu=menu)
        add.pack(side="left")
        make_button(bar, "Edit", self.edit_selected, small=True).pack(side="left", padx=(6, 0))
        make_button(bar, "Delete", self.delete_selected, small=True).pack(side="left", padx=6)
        make_button(bar, "Preview", self.test_selected, small=True).pack(side="left")

        opts = tk.Frame(win, bg=CREAM)
        opts.pack(fill="x", padx=14, pady=(4, 0))
        self.v_paused = tk.BooleanVar(value=self.settings.paused)
        self.v_startup = tk.BooleanVar(value=self.settings.start_with_windows)
        ttk.Checkbutton(opts, text="Pause all reminders", variable=self.v_paused, command=lambda: self.set_paused(self.v_paused.get())).pack(side="left")
        ttk.Checkbutton(opts, text="Start with Windows", variable=self.v_startup, command=self._on_startup).pack(side="left", padx=14)

        foot = tk.Frame(win, bg=CREAM)
        foot.pack(fill="x", padx=14, pady=(6, 10))
        note = "Runs in the background: use the tray icon near the clock. Closing this window keeps Desktop Pet running."
        if not self.tray_ok:
            note = "The tray icon is unavailable here, so closing this window minimises it instead."
        tk.Label(foot, text=note, font=(FONT, 8), bg=CREAM, fg=SOFT, justify="left", wraplength=int(360 * s)).pack(side="left")
        make_button(foot, "Quit", self.quit, small=True).pack(side="right")

    # ---- list
    def refresh(self) -> None:
        if self.tree is None or self.manager is None:
            return
        selected = self.tree.selection()
        now = datetime.now()
        self.tree.delete(*self.tree.get_children())
        for r in self.reminders:
            if self.settings.paused:
                nxt = "paused"
            elif not r.enabled:
                nxt = "off"
            else:
                nxt = describe_due(self.sched.next_due(r.id), now)
            self.tree.insert("", "end", iid=r.id, values=("\u2714" if r.enabled else "", r.name, r.schedule_text(), nxt))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def _refresh_loop(self) -> None:
        if self.manager is not None and self.manager.winfo_viewable():
            self.refresh()
        self.root.after(15000, self._refresh_loop)

    def _selected(self):
        sel = self.tree.selection() if self.tree is not None else ()
        return next((r for r in self.reminders if sel and r.id == sel[0]), None)

    def _on_tree_click(self, event) -> None:
        if self.tree.identify("region", event.x, event.y) == "cell" and self.tree.identify_column(event.x) == "#1":
            row = self.tree.identify_row(event.y)
            r = next((x for x in self.reminders if x.id == row), None)
            if r:
                r.enabled = not r.enabled
                self._changed()

    # ---- editing
    def add_from_template(self, key: str) -> None:
        dlg = ReminderDialog(self, core.new_from_template(key), "New reminder")
        if dlg.result:
            self.reminders.append(dlg.result)
            self._changed()

    def edit_selected(self) -> None:
        r = self._selected()
        if not r:
            self.inform("Pick a reminder from the list first, then press Edit.")
            return
        dlg = ReminderDialog(self, r, "Edit reminder")
        if dlg.result:
            self.reminders[self.reminders.index(r)] = dlg.result
            self._changed()

    def delete_selected(self) -> None:
        r = self._selected()
        if r is None:
            self.inform("Nothing is selected. Click a reminder in the list, then press Delete.")
        elif self.confirm(f"Delete the reminder '{r.name}'?", yes="Delete", no="Keep it"):
            self.reminders.remove(r)
            self._changed()

    def test_selected(self) -> None:
        r = self._selected()
        if not r:
            self.inform("Pick a reminder from the list first, then press Preview.")
            return
        self._close_popup()
        self._open_speech(r, test=True)

    # ---- cartoon message pop-ups (instead of plain Windows message boxes)
    def say(self, text, buttons=("OK",), title="Desktop Pet", pet=None, parent=None) -> int:
        selected = self._selected()
        pet = pet or (selected.pet if selected else (self.reminders[0].pet if self.reminders else "mochi"))
        return MessageWindow(self, text, title, buttons, pet, parent or self.manager).run()

    def inform(self, text, parent=None, pet=None) -> None:
        self.say(text, ("OK",), pet=pet, parent=parent)

    def confirm(self, text, yes="Yes", no="No", parent=None) -> bool:
        return self.say(text, (yes, no), parent=parent) == 0

    def _changed(self) -> None:
        self.reminders = [r.normalized() for r in self.reminders]
        self.sched.set_reminders(self.reminders, datetime.now())
        self._save()
        self.refresh()

    def _save(self) -> None:
        try:
            self.store.save(self.reminders, self.settings)
        except OSError as ex:
            log_error(f"save failed: {ex}")

    def _on_startup(self) -> None:
        want = self.v_startup.get()
        ok, message = winutil.set_startup(want, str(SCRIPT))
        if not ok:
            self.v_startup.set(False)
            want = False
            self.inform(message)
        self.settings.start_with_windows = want
        self._save()

    # ---- the heartbeat
    def _tick(self) -> None:
        try:
            self._ticks += 1
            result = self.sched.tick(datetime.now())
            if result.jumped:
                self.queue.clear()
                self._close_popup()
            self.queue.extend(result.due)
            self._show_next()
        except Exception as ex:                       # never let a bug stop the reminders
            log_error(f"tick failed: {ex!r}")
        self.root.after(1000, self._tick)

    def _show_next(self) -> None:
        if self.popup is not None or not self.queue:
            return
        if winutil.is_fullscreen():                   # wait politely; it will appear once the full-screen app is gone
            return
        r = self.queue.pop(0)
        if not any(x.id == r.id for x in self.reminders):
            return self._show_next()
        try:
            self._open_speech(r)
        except Exception as ex:
            log_error(f"speech window failed: {ex!r}")
            self.popup = None
            self.sched.skip(r.id, datetime.now())

    def _open_speech(self, reminder: core.Reminder, test: bool = False) -> None:
        self.popup = SpeechWindow(self, reminder, test=test)

    def _close_popup(self) -> None:
        popup, self.popup = self.popup, None
        if popup:
            popup.close()

    def _after_popup(self, popup) -> None:
        if self.popup is popup:
            self.popup = None
        popup.close()
        self.root.after(700, self._show_next)

    # ---- answers from the speech window
    def on_done(self, popup) -> None:
        if not popup.test:
            self.sched.done(popup.reminder.id, datetime.now())
        self._after_popup(popup)
        self.refresh()

    def on_skip(self, popup) -> None:
        if not popup.test:
            self.sched.skip(popup.reminder.id, datetime.now())
        self._after_popup(popup)
        self.refresh()

    def on_snooze(self, popup) -> None:
        if not popup.test:
            self.sched.snooze(popup.reminder.id, popup.reminder.snooze_min, datetime.now())
        self._after_popup(popup)
        self.refresh()

    def quit(self) -> None:
        self._close_popup()
        self.tray.stop()
        self.root.destroy()


def main(argv) -> None:
    if not winutil.acquire_single_instance():
        winutil.message_box("Desktop Pet", "Desktop Pet is already running in the background. Use its icon near the clock.")
        return
    try:
        app = App(minimized="--minimized" in argv)
        app.run()
    except Exception as ex:
        log_error(f"startup failed: {ex!r}")
        winutil.message_box("Desktop Pet could not start", f"{ex}\n\nDetails are in %AppData%\\DesktopPet\\log.txt")
