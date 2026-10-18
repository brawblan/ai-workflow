## ADDED cart.R1: Add an item

The cart adds the quantity to the quantity that the item already has.

### Scenario: Add the same item two times

- WHEN a shopper adds 2 of "pen" and then 3 of "pen"
- THEN the cart has 5 of "pen"

## ADDED cart.R2: Remove an item

The cart removes all of an item. An item that is not in the cart is an error.

### Scenario: Remove an item that is not in the cart

- WHEN a shopper removes "ink" from a cart with no "ink"
- THEN the cart raises KeyError
