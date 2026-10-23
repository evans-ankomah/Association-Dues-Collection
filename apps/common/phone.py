import re

_DIGITS = re.compile(r"\D+")


def normalize_gh_phone(value: str | None) -> str | None:
    """Normalise a Ghanaian phone number to 233XXXXXXXXX. Returns None for blanks.

    Raises ValueError when the number can't be a Ghanaian mobile number.
    """
    if not value or not value.strip():
        return None
    digits = _DIGITS.sub("", value)
    if digits.startswith("00233"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "233" + digits[1:]
    elif len(digits) == 9:
        digits = "233" + digits
    if not (digits.startswith("233") and len(digits) == 12):
        raise ValueError("Enter a Ghanaian number such as 024 123 4567 or +233 24 123 4567.")
    return digits
