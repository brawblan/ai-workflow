"""The shopping cart."""

from dataclasses import dataclass


@dataclass
class Line:
    name: str
    price: int  # cents for one item
    quantity: int


class Cart:
    """The items that a shopper wants to buy, by name."""

    def __init__(self) -> None:
        self.lines: dict[str, Line] = {}

    def add(self, name: str, price: int, quantity: int = 1) -> None:
        if name in self.lines:
            self.lines[name].quantity += quantity
        else:
            self.lines[name] = Line(name, price, quantity)

    def remove(self, name: str) -> None:
        del self.lines[name]

    def total(self) -> int:
        return sum(line.price * line.quantity for line in self.lines.values())
