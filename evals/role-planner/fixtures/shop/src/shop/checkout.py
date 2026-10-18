"""Checkout: the amount that the shopper pays."""

from shop.cart import Cart


def amount_due(cart: Cart) -> int:
    """Return the amount to pay, in cents."""
    return cart.total()
