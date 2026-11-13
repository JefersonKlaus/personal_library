"""The selection rules on their own (no interface): click, Ctrl, Shift, anchor."""
from src.ui.selection import Selection

ORDER = [10, 20, 30, 40, 50]  # book ids in the order shown


def test_click_selects_only_that_book():
    selection = Selection()
    selection.click(20, ORDER)
    selection.click(40, ORDER)
    assert selection.ids == {40} and selection.anchor == 40 and 40 in selection


def test_ctrl_click_adds_and_takes_out():
    selection = Selection()
    selection.click(10, ORDER)
    selection.click(30, ORDER, ctrl=True)
    selection.click(50, ORDER, ctrl=True)
    assert selection.ids == {10, 30, 50}
    selection.click(30, ORDER, ctrl=True)
    assert selection.ids == {10, 50} and selection.anchor == 30  # out, but still the anchor


def test_shift_click_selects_the_range_in_the_order_shown():
    selection = Selection()
    selection.click(20, ORDER)
    selection.click(40, ORDER, shift=True)
    assert selection.ids == {20, 30, 40}
    selection.click(10, ORDER, shift=True)  # same anchor, other direction
    assert selection.ids == {10, 20} and selection.anchor == 20


def test_shift_click_without_anchor_is_a_click():
    selection = Selection()
    selection.click(30, ORDER, shift=True)
    assert selection.ids == {30} and selection.anchor == 30


def test_ctrl_shift_click_adds_the_range():
    selection = Selection()
    selection.click(10, ORDER)
    selection.click(30, ORDER, ctrl=True)
    selection.click(50, ORDER, shift=True, ctrl=True)
    assert selection.ids == {10, 30, 40, 50}


def test_anchor_hidden_by_a_filter():
    """The anchor is not among the books shown: the click selects only the book."""
    selection = Selection()
    selection.click(20, ORDER)
    selection.click(50, [40, 50], shift=True)
    assert selection.ids == {50}


def test_count_in_counts_only_the_books_shown():
    selection = Selection()
    selection.click(10, ORDER)
    selection.click(50, ORDER, shift=True)
    assert selection.count_in(ORDER) == 5 and selection.count_in([10, 99]) == 1
