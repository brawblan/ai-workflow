import unittest

from shop.cart import Cart


class CartTotal(unittest.TestCase):
    def test_sum_of_lines(self) -> None:
        cart = Cart()
        cart.add("pen", 150, 2)
        self.assertEqual(cart.total(), 300)

    def test_discount_line_lowers_total(self) -> None:
        cart = Cart()
        cart.add("pen", 150)
        cart.add("code SAVE", -50)
        self.assertEqual(cart.total(), 100)
