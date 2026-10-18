# SHOP-3: Add items to the cart

## Understanding

A shopper puts items in a cart before checkout. Personas: shopper

## Files to change

- `src/shop/cart.py`

## Approach

A `Cart` keeps one line for each item name. A second add of the same item adds to its quantity.

## Acceptance criteria coverage

1. Add an item: `shopper.J1`, `cart.R1`. Verified by a unit test.
2. A cart holds at most 20 items: `shopper.J1`, `cart.R2`. Verified by a unit test.

## Out of scope and risks

Prices from the stock system are out of scope.

## Open questions

None.
