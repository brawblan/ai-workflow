"""Money helpers. All amounts are whole cents."""


def format_money(cents: int) -> str:
    """Return the amount in the form that the shop shows, for example "$1,234.50"."""
    sign = "-" if cents < 0 else ""
    dollars, rest = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{rest:02d}"
