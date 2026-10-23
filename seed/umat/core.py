"""Shared generation context: deterministic randomness, row creation against the schema, time and money helpers."""
import random
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from .config import UTC
from .schema import TABLES

AUTO_COLUMNS = ("id", "created_at", "updated_at")


class Ctx:
    def __init__(self, seed, as_of):
        self.seed = seed
        self.as_of = as_of
        self.tables = {}
        self.ref = {}  # lookups shared between builders
        self._uuid_rngs = {}

    def stream(self, name):
        """Independent RNG per builder so editing one area doesn't reshuffle the rest."""
        return random.Random(f"{self.seed}:{name}")

    def new_id(self, table):
        rng = self._uuid_rngs.setdefault(table, random.Random(f"{self.seed}:uuid:{table}"))
        return str(uuid.UUID(int=rng.getrandbits(128), version=4))

    def add(self, table, created_at, updated_at=None, **fields):
        columns = TABLES[table]
        unknown = set(fields) - set(columns)
        if unknown:
            raise KeyError(f"{table}: unknown columns {sorted(unknown)}")
        updated_at = max(created_at, updated_at or created_at)
        row = {"id": self.new_id(table), "created_at": created_at, "updated_at": min(updated_at, self.as_of)}
        for col in columns:
            if col not in AUTO_COLUMNS:
                row[col] = fields.get(col)
        self.tables.setdefault(table, []).append(row)
        return row


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def at(day, hour=9, minute=0, second=0):
    return datetime.combine(day, time(hour, minute, second), tzinfo=UTC)


def rand_time(rng, day, hours=(8, 20)):
    """Random timestamp on `day` with the hour drawn from `hours` (inclusive range or weighted dict)."""
    if isinstance(hours, dict):
        hour = rng.choices(list(hours), list(hours.values()))[0]
    else:
        hour = rng.randint(*hours)
    return at(day, hour, rng.randint(0, 59), rng.randint(0, 59))


def days_between(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def weighted_day(rng, start, end, weight_fn):
    days = [d for d in days_between(start, end)]
    weights = [max(weight_fn(d), 0.0) for d in days]
    if not days or sum(weights) == 0:
        return start
    return rng.choices(days, weights)[0]


def holiday_factor(day):
    """Quieter periods: Christmas/New Year break and the long vacation."""
    if (day.month == 12 and day.day >= 15) or (day.month == 1 and day.day <= 12):
        return 0.15
    if day.month in (6, 7) or (day.month == 8 and day.day < 20):
        return 0.1
    return 1.0


# Evening-heavy hours for mobile money; office hours for cash and bank.
MOMO_HOURS = {7: 2, 8: 4, 9: 5, 10: 5, 11: 5, 12: 6, 13: 6, 14: 5, 15: 5, 16: 6, 17: 7, 18: 9, 19: 10, 20: 10, 21: 9,
              22: 6, 23: 3}
OFFICE_HOURS = {8: 3, 9: 6, 10: 8, 11: 8, 12: 7, 13: 6, 14: 7, 15: 6, 16: 4}


def to_date(value):
    return value.date() if isinstance(value, datetime) else value


def is_weekend(day):
    return day.weekday() >= 5


def next_weekday(day):
    while is_weekend(day):
        day += timedelta(days=1)
    return day

