"""A small store of text notes."""


class Notes:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, text: str) -> int:
        """Save a note and return its number, from 1."""
        self.items.append(text)
        return len(self.items)

    def list(self) -> list[str]:
        return [f"{n}. {text}" for n, text in enumerate(self.items, start=1)]

    def delete(self, number: int) -> None:
        """Delete the note with this number, from 1."""
        del self.items[number]
