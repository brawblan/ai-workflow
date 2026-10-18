"""Discount codes from the marketing team. The team adds and ends codes each month."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Code:
    percent: int
    ends: date  # the last day that the code is valid


CODES = {
    "SAVE10": Code(percent=10, ends=date(2026, 12, 31)),
    "SPRING5": Code(percent=5, ends=date(2026, 5, 31)),
}
