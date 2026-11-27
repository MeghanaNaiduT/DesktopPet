import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_pet.core import (Reminder, Scheduler, Settings, Store, default_reminders, new_from_template,
                              parse_hhmm, TEMPLATES)

T0 = datetime(2026, 1, 5, 10, 0, 0)


def run(s: Scheduler, start: datetime, seconds: int, step: int = 1):
    """Tick once per `step` seconds; return (last_time, list of (time, reminder_name))."""
    fired = []
    t = start
    for _ in range(0, seconds, step):
        t += timedelta(seconds=step)
        res = s.tick(t)
        fired += [(t, r.name) for r in res.due]
    return t, fired


def make(**kw) -> Reminder:
    base = dict(id="a", name="Water", kind="interval", interval_min=10)
    base.update(kw)
    return Reminder(**base).normalized()


class SchedulerTests(unittest.TestCase):
    def sched(self, *reminders):
        s = Scheduler(T0)
        s.set_reminders(list(reminders), T0)
        return s

    def test_interval_fires_once_when_due(self):
        s = self.sched(make())
        t, fired = run(s, T0, 9 * 60 + 59)
        self.assertEqual(fired, [])
        t, fired = run(s, t, 5)
        self.assertEqual(len(fired), 1)
        t, fired = run(s, t, 3600)           # popup never answered: still no repeat
        self.assertEqual(fired, [])

    def test_done_and_skip_restart_full_interval(self):
        for answer in ("done", "skip"):
            s = self.sched(make())
            t, fired = run(s, T0, 601)
            self.assertEqual(len(fired), 1)
            getattr(s, answer)("a", t)
            t2, fired = run(s, t, 9 * 60)
            self.assertEqual(fired, [], answer)
            t2, fired = run(s, t2, 90)
            self.assertEqual(len(fired), 1, answer)

    def test_snooze_fires_once_at_chosen_time(self):
        s = self.sched(make())
        t, _ = run(s, T0, 601)
        s.snooze("a", 5, t)
        t2, fired = run(s, t, 4 * 60 + 50)
        self.assertEqual(fired, [])
        t2, fired = run(s, t2, 20)
        self.assertEqual(len(fired), 1)
        t2, fired = run(s, t2, 1800)
        self.assertEqual(fired, [])

    def test_sleep_gap_does_not_fire_stale_reminder(self):
        s = self.sched(make())
        t, _ = run(s, T0, 300)
        woke = t + timedelta(hours=8)
        res = s.tick(woke)
        self.assertTrue(res.jumped)
        self.assertEqual(res.due, [])
        t2, fired = run(s, woke, 9 * 60)
        self.assertEqual(fired, [])
        t2, fired = run(s, t2, 90)
        self.assertEqual(len(fired), 1)

    def test_sleep_gap_while_popup_open_clears_it(self):
        s = self.sched(make())
        t, fired = run(s, T0, 601)
        self.assertEqual(len(fired), 1)
        res = s.tick(t + timedelta(hours=2))
        self.assertTrue(res.jumped)
        # the reminder may fire again only after a fresh full interval
        t2, fired = run(s, t + timedelta(hours=2), 9 * 60)
        self.assertEqual(fired, [])

    def test_fixed_times(self):
        s = self.sched(make(kind="times", times=["10:30", "12:00"]))
        t, fired = run(s, T0, 29 * 60, step=5)
        self.assertEqual(fired, [])
        t, fired = run(s, t, 120, step=5)
        self.assertEqual(len(fired), 1)
        s.done("a", t)
        self.assertEqual(s.next_due("a"), datetime(2026, 1, 5, 12, 0))

    def test_fixed_time_missed_while_asleep_is_skipped(self):
        s = self.sched(make(kind="times", times=["10:30"]))
        res = s.tick(datetime(2026, 1, 5, 11, 0))      # a jump past the time
        self.assertTrue(res.jumped)
        self.assertEqual(res.due, [])
        self.assertEqual(s.next_due("a"), datetime(2026, 1, 6, 10, 30))

    def test_active_hours_hold_reminders_outside_the_window(self):
        r = make(interval_min=10, active_from="12:00", active_to="18:00")
        s = self.sched(r)
        t, fired = run(s, T0, 3600, step=5)            # 10:00-11:00 is outside the window
        self.assertEqual(fired, [])
        self.assertEqual(s.next_due("a"), datetime(2026, 1, 5, 12, 10))

    def test_overnight_active_window(self):
        r = make(active_from="22:00", active_to="06:00")
        from desktop_pet.core import _in_window
        self.assertTrue(_in_window(r, datetime(2026, 1, 5, 23, 0)))
        self.assertTrue(_in_window(r, datetime(2026, 1, 6, 5, 0)))
        self.assertFalse(_in_window(r, datetime(2026, 1, 5, 12, 0)))

    def test_pause_and_resume(self):
        s = self.sched(make())
        s.set_paused(True, T0)
        t, fired = run(s, T0, 3600, step=5)
        self.assertEqual(fired, [])
        s.set_paused(False, t)
        t2, fired = run(s, t, 9 * 60)
        self.assertEqual(fired, [])
        t2, fired = run(s, t2, 90)
        self.assertEqual(len(fired), 1)

    def test_disabled_reminder_never_fires(self):
        s = self.sched(make(enabled=False))
        t, fired = run(s, T0, 7200, step=5)
        self.assertEqual(fired, [])
        self.assertIsNone(s.next_due("a"))

    def test_editing_other_fields_keeps_countdown_but_new_interval_restarts(self):
        s = self.sched(make())
        t, _ = run(s, T0, 300)
        due_before = s.next_due("a")
        s.set_reminders([make(message="new text")], t)
        self.assertEqual(s.next_due("a"), due_before)
        s.set_reminders([make(interval_min=30)], t)
        self.assertEqual(s.next_due("a"), t + timedelta(minutes=30))

    def test_two_reminders_are_independent(self):
        s = self.sched(make(id="a", name="A", interval_min=5), make(id="b", name="B", interval_min=7))
        t, fired = run(s, T0, 8 * 60)
        self.assertEqual([n for _, n in fired], ["A", "B"])


class ModelAndStoreTests(unittest.TestCase):
    def test_normalize_clamps_everything(self):
        r = Reminder(name="  ", pet="dragon", kind="weird", interval_min=-4, times=["25:00", "9:05", "bad"],
                     break_seconds=999999, snooze_min=0, active_from="x", active_to="99:99").normalized()
        self.assertEqual((r.name, r.pet, r.kind), ("Reminder", "mochi", "interval"))
        self.assertEqual(r.interval_min, 1)
        self.assertEqual(r.times, ["09:05"])
        self.assertEqual((r.break_seconds, r.snooze_min), (3600, 1))
        self.assertEqual((r.active_from, r.active_to), ("00:00", "23:59"))
        self.assertTrue(r.id)

    def test_parse_hhmm(self):
        self.assertEqual(parse_hhmm("9:05"), (9, 5))
        self.assertIsNone(parse_hhmm("24:00"))
        self.assertIsNone(parse_hhmm("abc"))

    def test_templates_cover_the_use_cases(self):
        for key in TEMPLATES:
            self.assertTrue(new_from_template(key).id)
        names = {r.name for r in default_reminders()}
        self.assertEqual(names, {"Eye break", "Water"})

    def test_store_roundtrip_first_run_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "x" / "data.json")
            rem, st = store.load()
            self.assertTrue(store.first_run)
            self.assertEqual(len(rem), 2)

            rem.append(new_from_template("Stretch"))
            store.save(rem, Settings(start_with_windows=False, paused=True))
            store2 = Store(store.path)
            rem2, st2 = store2.load()
            self.assertFalse(store2.first_run)
            self.assertEqual([r.name for r in rem2], ["Eye break", "Water", "Stretch"])
            self.assertEqual((st2.start_with_windows, st2.paused), (False, True))

            store.path.write_text("{not json", encoding="utf-8")
            rem3, _ = Store(store.path).load()
            self.assertEqual(len(rem3), 2)
            self.assertTrue(store.path.with_suffix(".bad").exists())

    def test_store_rejects_oversized_and_garbage_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "data.json"
            p.write_text(json.dumps({"reminders": [{"name": 5, "interval_min": "abc", "times": "oops", "pet": None}]}))
            rem, _ = Store(p).load()
            self.assertEqual(len(rem), 1)
            self.assertEqual(rem[0].interval_min, 30)
            p.write_text(" " * (300 * 1024))
            rem, _ = Store(p).load()
            self.assertEqual(len(rem), 2)


class AssetTests(unittest.TestCase):
    def test_every_pet_has_a_sprite_sheet_at_every_size(self):
        from desktop_pet.core import PETS
        assets = Path(__file__).resolve().parents[1] / "desktop_pet" / "assets"
        missing = [f"{pet}_{h}.png" for pet in PETS for h in (115, 170) if not (assets / f"{pet}_{h}.png").exists()]
        self.assertEqual(missing, [])
        self.assertTrue((assets / "app.ico").exists())

    def test_sheets_have_the_expected_grid(self):
        try:
            from PIL import Image  # only needed by this test, not by the app
        except ImportError:
            self.skipTest("Pillow not installed")
        from desktop_pet.core import PETS
        assets = Path(__file__).resolve().parents[1] / "desktop_pet" / "assets"
        for pet in PETS:
            w, h = Image.open(assets / f"{pet}_115.png").size
            self.assertEqual((w % 6, h % 4), (0, 0), pet)


class OfflineGuaranteeTests(unittest.TestCase):
    FORBIDDEN = ("import socket", "import urllib", "import http", "import requests", "import ssl", "import smtplib",
                 "import ftplib", "import xmlrpc", "import asyncio", "from urllib", "from http", "from socket",
                 "import webbrowser", "import subprocess", "import telnetlib")

    def test_source_never_imports_networking(self):
        root = Path(__file__).resolve().parents[1] / "desktop_pet"
        bad = []
        for f in list(root.glob("*.py")) + [root.parent / "DesktopPet.pyw"]:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if any(line.strip().startswith(w) for w in self.FORBIDDEN):
                    bad.append(f"{f.name}:{n}: {line.strip()}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
