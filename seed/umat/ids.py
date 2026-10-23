"""Formats for human-facing identifiers: student numbers, phone numbers, payment references, receipt numbers."""
import string

from .config import NETWORKS, STUDENT_NUMBER_PATTERN, STUDENT_NUMBER_PREFIX

_ALNUM = string.ascii_uppercase + string.digits


def student_number(entry_year, serial):
    return STUDENT_NUMBER_PATTERN.format(prefix=STUDENT_NUMBER_PREFIX, entry_year=entry_year, serial=serial)


def phone_number(rng):
    """Return (network wallet name, number normalised as 233XXXXXXXXX)."""
    name, prefixes, _ = rng.choices(NETWORKS, [n[2] for n in NETWORKS])[0]
    return name, f"233{rng.choice(prefixes)}{rng.randint(0, 9_999_999):07d}"


def momo_transaction_id(rng):
    return str(rng.randint(10_000_000_000, 99_999_999_999))


def paystack_reference(rng):
    return "DH-CSE-" + "".join(rng.choice(_ALNUM) for _ in range(10))


def paystack_transaction_id(rng):
    return str(rng.randint(3_800_000_000, 4_999_999_999))


def bank_reference(rng, day):
    """Core-banking style funds-transfer reference, e.g. FT25270Q8K2M."""
    return f"FT{day:%y}{day.timetuple().tm_yday:03d}" + "".join(rng.choice(_ALNUM) for _ in range(5))


def receipt_number(dept_code, year, seq):
    return f"{dept_code}-{year}-{seq:06d}"


def masked_phone(number):
    return f"{number[:5]}****{number[-3:]}"
