"""A cart: lines of items with a price in cents. A discount is a line with a negative price."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Line:
    name: str
    price: int  # cents. A negative price is a discount.
    quantity: int = 1


class Cart:
    def __init__(self) -> None:
        self.lines: list[Line] = []

    def add(self, name: str, price: int, quantity: int = 1) -> None:
        self.lines.append(Line(name, price, quantity))

    def total(self) -> int:
        """Return the amount due in cents. The total is never below zero."""
        return max(0, sum(line.price * line.quantity for line in self.lines))
