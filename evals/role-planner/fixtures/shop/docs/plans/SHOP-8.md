# SHOP-8: Remove the item limit

## Understanding

Shoppers who buy for an office need more than 20 items. Personas: shopper

## Files to change

- `src/shop/cart.py`

## Approach

Remove the limit check from `Cart.add`.

## Acceptance criteria coverage

1. A cart holds any number of items: `shopper.J1`, `cart.R2` removed. Verified by a unit test.

## Out of scope and risks

None.

## Open questions

None.
