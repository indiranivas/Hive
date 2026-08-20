"""UTC coercion.

Postgres hands back timezone-aware datetimes; SQLite hands back naive ones for
the same column. Everything read from the DB or a connector payload goes through
here so comparisons never mix the two.
"""

from __future__ import annotations

from datetime import UTC, datetime


def to_utc(value: datetime | None) -> datetime | None:
    """Coerce a datetime to UTC-aware. Naive values are assumed to be UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_utc(value: datetime | str | None) -> datetime:
    """Parse ISO-8601 (or a datetime) into a UTC-aware datetime; None means now."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            value = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
    coerced = to_utc(value)
    assert coerced is not None
    return coerced
