"""A fixed clock for the lab.

The seeded dataset is anchored to a fixed moment in time, so "overdue" and
"open for more than 3 days" mean the same thing every time the lab runs. That
keeps the numbers in the docs reproducible.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

ANCHOR_NOW = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def now() -> datetime:
    """The moment the lab treats as now."""
    override = os.environ.get("LAB_NOW")
    if override:
        try:
            return datetime.fromisoformat(override).astimezone(timezone.utc)
        except ValueError:
            pass
    return ANCHOR_NOW


def now_iso() -> str:
    return now().isoformat()


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def days_ago(days: float, anchor: datetime | None = None) -> datetime:
    base = anchor or now()
    return base - timedelta(days=days)


def hours_ago(hours: float, anchor: datetime | None = None) -> datetime:
    base = anchor or now()
    return base - timedelta(hours=hours)
