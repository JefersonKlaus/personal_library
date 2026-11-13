"""Which books of the gallery are selected, with the rules of a file manager.

Only the rules live here (no Flet): the gallery turns clicks into calls and highlights
the cards. `order` is the list of book ids in the order shown (search, series and sort
applied), which is what a Shift+click range follows, across pages.
"""
from __future__ import annotations


class Selection:
    def __init__(self) -> None:
        self.ids: set[int] = set()
        self.anchor: int | None = None  # where a Shift+click range starts (last click)

    def __contains__(self, book_id: int) -> bool:
        return book_id in self.ids

    def click(self, book_id: int, order: list[int], shift: bool = False,
              ctrl: bool = False) -> None:
        """* click: only this book;
        * Ctrl+click: adds the book, or takes it out if it was in;
        * Shift+click: every book from the last click to this one;
        * Ctrl+Shift+click: adds that range to what was already selected."""
        if shift and self.anchor is not None:
            self.extend_to(book_id, order, add=ctrl)
        elif ctrl:
            self.toggle(book_id)
        else:
            self.only(book_id)

    def only(self, book_id: int) -> None:
        """Selects only this book; it becomes the start of the next range."""
        self.ids, self.anchor = {book_id}, book_id

    def toggle(self, book_id: int) -> None:
        """The other books stay selected; the book becomes the start of the next range,
        even when it was taken out."""
        self.ids, self.anchor = self.ids ^ {book_id}, book_id

    def extend_to(self, book_id: int, order: list[int], add: bool = False) -> None:
        """Every book from the anchor to this one, inclusive. The anchor stays, so further
        Shift+clicks move the end. With `add` the range joins the selection."""
        if self.anchor not in order or book_id not in order:  # anchor hidden by a filter
            self.only(book_id)
            return
        first, last = sorted((order.index(self.anchor), order.index(book_id)))
        books = set(order[first:last + 1])
        self.ids = self.ids | books if add else books

    def count_in(self, order: list[int]) -> int:
        """How many of the books shown are selected (a range can reach other pages)."""
        return sum(1 for book_id in order if book_id in self.ids)
