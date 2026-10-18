---
apply_order: 1
---

## ADDED cart.R1: Add an item

The cart MUST add the quantity to the quantity that the item already has.

### Scenario: Add the same item two times

- WHEN a shopper adds 2 of "pen" and then 3 of "pen"
- THEN the cart has 5 of "pen"

## ADDED cart.R2: At most 20 items

The cart MUST NOT hold more than 20 items.

### Scenario: Add the twenty-first item

- WHEN a shopper with 20 items in the cart adds 1 more
- THEN the cart refuses the item
