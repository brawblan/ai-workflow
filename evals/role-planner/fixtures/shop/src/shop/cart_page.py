"""The text of the cart page."""

from shop.cart import Cart
from shop.money import format_money


def render_cart(cart: Cart) -> str:
    if not cart.lines:
        return "Your cart is emtpy."
    rows = [f"{line.name} x{line.quantity}  {format_money(line.price * line.quantity)}"
            for line in cart.lines.values()]
    rows.append(f"Total  {format_money(cart.total())}")
    return "\n".join(rows)
