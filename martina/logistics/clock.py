"""Simulation time.

The control tower runs on its own clock, measured in minutes since an epoch
(midnight at the start of the simulated history). Two helpers move time
forward the way the business does: trucks drive only between 05:00 and
22:00, and time on a customer's site only counts inside its receiving window.
"""
from __future__ import annotations

from datetime import datetime, timedelta

DAY = 1440.0
DRIVE_START, DRIVE_END = 5 * 60, 22 * 60


def minute_of_day(t: float) -> float:
    return t % DAY


def day_start(t: float) -> float:
    return t - (t % DAY)


def advance_window(t: float, minutes: float, open_min: float, close_min: float) -> float:
    """Move forward `minutes` of time that only counts between open and close."""
    left = max(0.0, minutes)
    for _ in range(400):                      # bounded: at most ~400 days
        m = t % DAY
        if m < open_min:
            t += open_min - m
            m = open_min
        elif m >= close_min:
            t += DAY - m + open_min
            m = open_min
        room = close_min - m
        if left <= room:
            return t + left
        left -= room
        t += room
    return t + left


def window_minutes_between(a: float, b: float, open_min: float, close_min: float) -> float:
    """Minutes inside the daily window between times a and b."""
    if b <= a:
        return 0.0
    total = 0.0
    d = day_start(a)
    while d < b:
        lo, hi = max(a, d + open_min), min(b, d + close_min)
        if hi > lo:
            total += hi - lo
        d += DAY
    return total


def drive(t: float, minutes: float) -> float:
    return advance_window(t, minutes, DRIVE_START, DRIVE_END)


def driving_minutes_between(a, b):
    return window_minutes_between(a, b, DRIVE_START, DRIVE_END)


class Clock:
    """Maps simulation minutes to calendar time."""

    def __init__(self, epoch: datetime):
        self.epoch = epoch

    def dt(self, t: float) -> datetime:
        return self.epoch + timedelta(minutes=float(t))

    def fmt(self, t: float, with_day=False) -> str:
        if t is None or t != t:
            return "-"
        d = self.dt(t)
        return d.strftime("%a %d %b %H:%M") if with_day else d.strftime("%H:%M")

    def minutes(self, when: datetime) -> float:
        return (when - self.epoch).total_seconds() / 60.0
