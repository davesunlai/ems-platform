"""Výpočet zúčtovacího období (start dle ČEZ, délka v měsících, recyklace)."""
from __future__ import annotations

import calendar
from datetime import date


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def current_period(billing_start: date, months: int, today: date) -> tuple[date, date]:
    """Vrátí [start, end) aktuálního období. Po konci období → další od nuly."""
    if not months or months <= 0:
        months = 12
    start = billing_start
    nxt = add_months(start, months)
    guard = 0
    while nxt <= today and guard < 2000:
        start, nxt = nxt, add_months(nxt, months)
        guard += 1
    return start, nxt


def month_keys(start: date, end: date, today: date) -> list[str]:
    """Klíče měsíců 'YYYY-MM' od startu do konce období (max do dneška)."""
    last = min(end, add_months(today, 1))
    keys, cur = [], date(start.year, start.month, 1)
    while cur < last:
        keys.append(f"{cur.year:04d}-{cur.month:02d}")
        cur = add_months(cur, 1)
    return keys
