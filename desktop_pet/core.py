"""Reminder data model and scheduler. Pure Python, no UI, no network. Everything here is unit-tested."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ----------------------------------------------------------------------------- pets

PETS = {
    "mochi": {"name": "Mochi", "kind": "Calico kitten"},
    "remi": {"name": "Remi", "kind": "Baby sloth"},
    "finn": {"name": "Finn", "kind": "Fennec fox"},
    "pogo": {"name": "Pogo", "kind": "Baby porcupine"},
    "boba": {"name": "Boba", "kind": "Hamster"},
}
PET_IDS = tuple(PETS)

_HHMM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def parse_hhmm(text: str) -> Optional[Tuple[int, int]]:
    m = _HHMM.match(text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if 0 <= h <= 23 and 0 <= mi <= 59 else None


def fmt_hhmm(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}"


# ----------------------------------------------------------------------------- reminder model


@dataclass
class Reminder:
    id: str = ""
    name: str = "Reminder"
    message: str = ""
    pet: str = "mochi"
    kind: str = "interval"            # "interval" = every N minutes, "times" = at fixed times of day
    interval_min: int = 30
    times: List[str] = field(default_factory=list)   # ["09:00", "13:30"] when kind == "times"
    break_seconds: int = 0            # 0 = just a nudge; >0 = offers a countdown (e.g. 20 for the eye exercise)
    snooze_min: int = 5
    sound: bool = False
    active_from: str = "00:00"        # only remind between these times
    active_to: str = "23:59"
    enabled: bool = True

    def normalized(self) -> "Reminder":
        """Return a copy with every field forced into a sane range."""
        r = Reminder(**asdict(self))
        r.id = r.id if isinstance(r.id, str) and r.id else uuid.uuid4().hex[:10]
        r.name = (str(r.name).strip() or "Reminder")[:40]
        r.message = str(r.message).strip()[:200]
        r.pet = r.pet if r.pet in PET_IDS else PET_IDS[0]
        r.kind = r.kind if r.kind in ("interval", "times") else "interval"
        r.interval_min = _clamp(r.interval_min, 1, 1440, 30)
        good = sorted({fmt_hhmm(*t) for t in (parse_hhmm(str(x)) for x in (r.times or [])) if t})
        r.times = good[:24]
        r.break_seconds = _clamp(r.break_seconds, 0, 3600, 0)
        r.snooze_min = _clamp(r.snooze_min, 1, 240, 5)
        r.sound = bool(r.sound)
        r.enabled = bool(r.enabled)
        r.active_from = fmt_hhmm(*(parse_hhmm(str(r.active_from)) or (0, 0)))
        r.active_to = fmt_hhmm(*(parse_hhmm(str(r.active_to)) or (23, 59)))
        return r

    @staticmethod
    def from_dict(d: dict) -> "Reminder":
        known = {k: d[k] for k in Reminder.__dataclass_fields__ if isinstance(d, dict) and k in d}
        return Reminder(**known).normalized()

    def schedule_text(self) -> str:
        if self.kind == "times":
            return "At " + ", ".join(self.times) if self.times else "No times set"
        m = self.interval_min
        if m % 60 == 0:
            h = m // 60
            return "Every hour" if h == 1 else f"Every {h} hours"
        return f"Every {m} min"


def _clamp(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


# Ready-made starting points (the user can edit everything).
TEMPLATES: Dict[str, Reminder] = {
    "Eye break (20-20-20)": Reminder(
        name="Eye break", pet="finn", kind="interval", interval_min=20, break_seconds=20,
        message="Look at something about 20 feet (6 metres) away for 20 seconds. Blink softly and naturally."),
    "Drink water": Reminder(
        name="Water", pet="boba", kind="interval", interval_min=60,
        message="Time for a glass of water."),
    "Stretch": Reminder(
        name="Stretch", pet="remi", kind="interval", interval_min=60, break_seconds=60,
        message="Stand up, roll your shoulders and stretch for a minute."),
    "Posture check": Reminder(
        name="Posture", pet="pogo", kind="interval", interval_min=30,
        message="Sit tall, relax your shoulders, unclench your jaw."),
    "Custom reminder": Reminder(name="My reminder", pet="mochi", kind="interval", interval_min=45, message=""),
}


def default_reminders() -> List[Reminder]:
    return [TEMPLATES["Eye break (20-20-20)"].normalized(), TEMPLATES["Drink water"].normalized()]


def new_from_template(key: str) -> Reminder:
    r = Reminder(**asdict(TEMPLATES[key]))
    r.id = ""
    return r.normalized()


# ----------------------------------------------------------------------------- storage


@dataclass
class Settings:
    start_with_windows: bool = True
    paused: bool = False


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "DesktopPet"


class Store:
    """One small JSON file in %AppData%\\DesktopPet. Corrupt or oversized files are set aside, never crash the app."""

    MAX_BYTES = 256 * 1024

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else data_dir() / "data.json"
        self.first_run = False

    def load(self) -> Tuple[List[Reminder], Settings]:
        self.first_run = not self.path.exists()
        if self.first_run:
            return default_reminders(), Settings()
        try:
            if self.path.stat().st_size > self.MAX_BYTES:
                raise ValueError("data file too large")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            reminders = [Reminder.from_dict(d) for d in raw.get("reminders", [])][:100]
            s = raw.get("settings", {})
            settings = Settings(bool(s.get("start_with_windows", True)), bool(s.get("paused", False)))
            return reminders, settings
        except (ValueError, OSError, AttributeError, TypeError):
            try:
                self.path.replace(self.path.with_suffix(".bad"))
            except OSError:
                pass
            return default_reminders(), Settings()

    def save(self, reminders: List[Reminder], settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "settings": asdict(settings), "reminders": [asdict(r) for r in reminders]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


# ----------------------------------------------------------------------------- scheduler

MAX_TICK_GAP = timedelta(seconds=30)      # a longer gap between ticks means the PC slept
MISSED_TIME_GRACE = timedelta(minutes=5)  # a fixed-time reminder this late is skipped, not shown


@dataclass
class TickResult:
    due: List[Reminder]
    jumped: bool   # True when the PC slept / the clock jumped: close any popups, nothing stale is shown


def _in_window(r: Reminder, t) -> bool:
    a, b = parse_hhmm(r.active_from), parse_hhmm(r.active_to)
    if not a or not b or a == b:
        return True
    cur = (t.hour, t.minute)
    return a <= cur <= b if a < b else (cur >= a or cur <= b)


def _next_window_start(r: Reminder, now: datetime) -> datetime:
    a = parse_hhmm(r.active_from) or (0, 0)
    start = now.replace(hour=a[0], minute=a[1], second=0, microsecond=0)
    return start if start > now else start + timedelta(days=1)


def _next_time(r: Reminder, after: datetime) -> Optional[datetime]:
    best = None
    for text in r.times:
        hm = parse_hhmm(text)
        if not hm:
            continue
        for day in (0, 1):
            cand = (after + timedelta(days=day)).replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
            if cand > after and (best is None or cand < best):
                best = cand
    return best


class Scheduler:
    """
    Decides when each reminder is due. Promises:
      * a reminder fires once, then waits for Done / Snooze / Skip before it is scheduled again
      * ignoring a popup just starts the normal interval again; nothing repeats
      * sleeping or a big clock jump never produces a stale reminder
      * pausing, disabling and active hours are respected
    Call tick(now) about once per second from the UI thread.
    """

    def __init__(self, now: datetime):
        self._reminders: Dict[str, Reminder] = {}
        self._due: Dict[str, Optional[datetime]] = {}
        self._active: set = set()          # reminders whose popup is currently open / queued
        self._last_tick = now
        self.paused = False

    # ---- configuration
    def set_reminders(self, reminders: List[Reminder], now: datetime) -> None:
        old = self._reminders
        self._reminders = {r.id: r for r in reminders}
        for rid, r in self._reminders.items():
            prev = old.get(rid)
            if prev is None or self._signature(prev) != self._signature(r):
                self._due[rid] = self._first_due(r, now)
                self._active.discard(rid)
        for rid in list(self._due):
            if rid not in self._reminders:
                del self._due[rid]
                self._active.discard(rid)

    @staticmethod
    def _signature(r: Reminder):
        return (r.enabled, r.kind, r.interval_min, tuple(r.times), r.active_from, r.active_to)

    def set_paused(self, paused: bool, now: datetime) -> None:
        was, self.paused = self.paused, paused
        if was and not paused:
            self._reschedule_all(now)

    # ---- queries
    def next_due(self, rid: str) -> Optional[datetime]:
        return self._due.get(rid)

    # ---- the clock
    def tick(self, now: datetime) -> TickResult:
        gap = now - self._last_tick
        self._last_tick = now
        if gap > MAX_TICK_GAP or gap < -MAX_TICK_GAP:
            self._reschedule_all(now)
            return TickResult([], True)
        if self.paused:
            return TickResult([], False)

        fired: List[Reminder] = []
        for rid, r in self._reminders.items():
            due = self._due.get(rid)
            if not r.enabled or due is None or rid in self._active or now < due:
                continue
            if r.kind == "times" and now - due > MISSED_TIME_GRACE:
                self._due[rid] = self._first_due(r, now)      # missed (e.g. asleep): skip it
                continue
            if not _in_window(r, now):
                self._due[rid] = self._after_window(r, now)
                continue
            self._active.add(rid)
            fired.append(r)
        return TickResult(fired, False)

    # ---- answers to a popup
    def done(self, rid: str, now: datetime) -> None:
        self._finish(rid, now)

    skip = done   # "Not now" and an ignored popup both simply restart the normal schedule

    def snooze(self, rid: str, minutes: int, now: datetime) -> None:
        if rid in self._reminders:
            self._active.discard(rid)
            self._due[rid] = now + timedelta(minutes=max(1, int(minutes)))

    # ---- internals
    def _finish(self, rid: str, now: datetime) -> None:
        self._active.discard(rid)
        r = self._reminders.get(rid)
        if r:
            self._due[rid] = self._first_due(r, now)

    def _reschedule_all(self, now: datetime) -> None:
        self._active.clear()
        for rid, r in self._reminders.items():
            self._due[rid] = self._first_due(r, now)

    def _first_due(self, r: Reminder, now: datetime) -> Optional[datetime]:
        if not r.enabled:
            return None
        if r.kind == "times":
            return _next_time(r, now)
        return now + timedelta(minutes=r.interval_min)

    def _after_window(self, r: Reminder, now: datetime) -> Optional[datetime]:
        if r.kind == "times":
            return _next_time(r, now)
        return _next_window_start(r, now) + timedelta(minutes=r.interval_min)
