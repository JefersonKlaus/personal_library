"""Selecting books in the gallery: click, Shift+click, Ctrl+click."""
import asyncio

from helpers import gestures, open_library, press_ctrl, press_shift, selected_titles


def test_one_click_only_selects(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    first, second = gallery.cards[0], gallery.cards[1]
    assert not any(card.selected for card in gallery.cards)
    gestures(first)[0](None)
    assert first.selected and gallery.selection.ids == {first.book.id}
    assert app.page.dialogs == []  # one click opens nothing
    gestures(second)[0](None)
    assert second.selected and not first.selected  # only one selected at a time
    assert [card.selected for card in gallery.cards].count(True) == 1
    first.control.content.on_secondary_tap_down(None)  # the right button selects as well
    assert first.selected and not second.selected and app.page.dialogs == []


def test_double_click_or_right_click_open_opens_the_details(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    card = gallery.cards[2]
    gestures(card)[1](None)  # two clicks
    assert len(app.page.dialogs) == 1 and card.selected
    assert app.page.dialogs[0].title.controls[0].value == card.book.title
    app.page.pop_dialog()
    other = gallery.cards[0]
    gestures(other)[2](None)  # right button > Abrir
    assert app.page.dialogs[0].title.controls[0].value == other.book.title
    assert other.selected and not card.selected


def test_selection_survives_search_and_sort(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    book_id = gallery.cards[1].book.id
    gestures(gallery.cards[1])[0](None)
    gallery.sort_dropdown.value = "title"
    asyncio.run(gallery.on_sort(None))  # grid redrawn
    assert [card.book.id for card in gallery.cards if card.selected] == [book_id]


def test_shift_click_selects_every_book_between_the_two_clicks(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    titles = [book.title for book in gallery.view]
    gestures(gallery.cards[0])[0](None)
    press_shift(app)
    gestures(gallery.cards[2])[0](None)
    assert selected_titles(gallery) == titles[0:3]
    assert [card.selected for card in gallery.cards] == [True, True, True, False]
    assert gallery.count_text.value == "4 livro(s) · 3 selecionados"
    assert app.page.dialogs == []  # selecting a range opens nothing


def test_shift_click_works_backwards_and_keeps_the_start(app, make_library, tmp_path):
    """Like a file manager: the first click is the anchor; each Shift+click moves the end."""
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    titles = [book.title for book in gallery.view]
    gestures(gallery.cards[2])[0](None)
    press_shift(app)
    gestures(gallery.cards[0])[0](None)  # upwards
    assert selected_titles(gallery) == titles[0:3]
    gestures(gallery.cards[3])[0](None)  # same start, new end: the range shrinks/moves
    assert selected_titles(gallery) == titles[2:4]


def test_click_without_shift_goes_back_to_a_single_book(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gestures(gallery.cards[0])[0](None)
    press_shift(app)
    gestures(gallery.cards[3])[0](None)
    assert len(gallery.selection.ids) == 4
    press_shift(app, down=False)
    gestures(gallery.cards[1])[0](None)
    assert gallery.selection.ids == {gallery.cards[1].book.id}
    assert gallery.count_text.value == "4 livro(s)"  # one selected: no count
    press_shift(app)
    gestures(gallery.cards[2])[0](None)  # the new anchor is the last plain click
    assert gallery.selection.ids == {gallery.cards[1].book.id, gallery.cards[2].book.id}


def test_shift_click_with_nothing_selected_selects_that_book(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    press_shift(app)
    gestures(gallery.cards[2])[0](None)
    assert gallery.selection.ids == {gallery.cards[2].book.id}
    gestures(gallery.cards[0])[0](None)  # ...and it became the anchor
    assert len(gallery.selection.ids) == 3


def test_shift_range_spans_pages(app, ui, make_library, tmp_path, monkeypatch):
    monkeypatch.setattr(ui.gallery_tab, "GALLERY_PAGE_SIZE", 3)
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gestures(gallery.cards[1])[0](None)  # page 1
    asyncio.run(gallery.on_next(None))
    press_shift(app)
    gestures(gallery.cards[0])[0](None)  # page 2 (the 4th book)
    assert selected_titles(gallery) == [book.title for book in gallery.view][1:4]
    assert gallery.cards[0].selected  # the card on screen is highlighted
    asyncio.run(gallery.on_prev(None))  # back on page 1, the range is still there
    assert [card.selected for card in gallery.cards] == [False, True, True]
    assert gallery.count_text.value == "4 livro(s) · 3 selecionados"


def test_shift_range_follows_the_search_and_sort(app, make_library, tmp_path):
    """The range is what is on screen: books hidden by the search are not selected."""
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gallery.sort_dropdown.value = "title"
    asyncio.run(gallery.on_sort(None))
    titles = [book.title for book in gallery.view]
    gestures(gallery.cards[0])[0](None)
    press_shift(app)
    gestures(gallery.cards[3])[0](None)
    assert selected_titles(gallery) == titles
    press_shift(app, down=False)
    gallery.search_field.value = "Tolkien"  # only The Hobbit (3rd by title)
    asyncio.run(gallery.on_search(None))
    gestures(gallery.cards[0])[0](None)  # the new anchor, chosen inside the search
    gallery.search_field.value = ""
    asyncio.run(gallery.on_search(None))
    press_shift(app)
    gestures(gallery.cards[0])[0](None)  # 1st by title
    assert titles.index("The Hobbit") == 2
    assert selected_titles(gallery) == titles[0:3]


def test_shift_click_when_the_start_is_hidden_selects_only_the_clicked_book(
        app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    hidden = next(card for card in gallery.cards if card.book.title == "Dom Casmurro")
    gestures(hidden)[0](None)
    gallery.search_field.value = "Hobbit"
    asyncio.run(gallery.on_search(None))
    press_shift(app)
    gestures(gallery.cards[0])[0](None)
    assert selected_titles(gallery) == ["The Hobbit"]


def test_right_click_keeps_a_range_and_double_click_opens_one_book(app, make_library,
                                                                  tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gestures(gallery.cards[0])[0](None)
    press_shift(app)
    gestures(gallery.cards[2])[0](None)
    press_shift(app, down=False)
    selected = set(gallery.selection.ids)
    gallery.cards[1].control.content.on_secondary_tap_down(None)  # inside the range
    assert gallery.selection.ids == selected
    gestures(gallery.cards[1])[2](None)  # right button > Abrir
    assert app.page.dialogs[0].title.controls[0].value == gallery.cards[1].book.title
    assert gallery.selection.ids == selected  # opening does not drop the range
    app.page.pop_dialog()
    gallery.cards[3].control.content.on_secondary_tap_down(None)  # outside the range
    assert gallery.selection.ids == {gallery.cards[3].book.id}


# ---------------------------------------------------------------- Ctrl+click (pick books)

def test_ctrl_click_adds_books_and_keeps_the_others(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    titles = [book.title for book in gallery.view]
    gestures(gallery.cards[0])[0](None)
    press_ctrl(app)
    gestures(gallery.cards[2])[0](None)
    gestures(gallery.cards[3])[0](None)
    assert selected_titles(gallery) == [titles[0], titles[2], titles[3]]  # not the one in between
    assert [card.selected for card in gallery.cards] == [True, False, True, True]
    assert gallery.count_text.value == "4 livro(s) · 3 selecionados"
    assert app.page.dialogs == []


def test_ctrl_click_on_a_selected_book_takes_it_out(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    press_ctrl(app)
    gestures(gallery.cards[0])[0](None)
    gestures(gallery.cards[1])[0](None)
    gestures(gallery.cards[0])[0](None)  # again: out
    assert gallery.selection.ids == {gallery.cards[1].book.id}
    gestures(gallery.cards[1])[0](None)
    assert gallery.selection.ids == set()  # everything can be taken out
    assert not any(card.selected for card in gallery.cards)


def test_plain_click_after_ctrl_goes_back_to_one_book(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    press_ctrl(app)
    gestures(gallery.cards[0])[0](None)
    gestures(gallery.cards[2])[0](None)
    press_ctrl(app, down=False)
    gestures(gallery.cards[3])[0](None)
    assert gallery.selection.ids == {gallery.cards[3].book.id}


def test_cmd_click_works_like_ctrl_click(app, make_library, tmp_path):
    """On macOS Ctrl+click is the right click, so Cmd (Meta) picks the books."""
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gestures(gallery.cards[0])[0](None)
    press_ctrl(app, key="Meta Left")
    gestures(gallery.cards[3])[0](None)
    assert gallery.selection.ids == {gallery.cards[0].book.id, gallery.cards[3].book.id}


def test_shift_click_after_ctrl_starts_at_the_last_ctrl_click(app, make_library, tmp_path):
    """Like a file manager: Shift+click replaces the picked books with a range that
    starts at the last (Ctrl+)click."""
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    titles = [book.title for book in gallery.view]
    gestures(gallery.cards[0])[0](None)
    press_ctrl(app)
    gestures(gallery.cards[2])[0](None)
    press_ctrl(app, down=False)
    press_shift(app)
    gestures(gallery.cards[3])[0](None)
    assert selected_titles(gallery) == titles[2:4]


def test_ctrl_shift_click_adds_a_range_to_the_picked_books(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    titles = [book.title for book in gallery.view]
    gestures(gallery.cards[0])[0](None)
    press_ctrl(app)
    gestures(gallery.cards[2])[0](None)  # picked: 1st and 3rd; anchor: 3rd
    press_shift(app)
    gestures(gallery.cards[3])[0](None)  # Ctrl+Shift: + 3rd..4th, the 1st stays
    assert selected_titles(gallery) == [titles[0], titles[2], titles[3]]


def test_ctrl_picks_survive_pages(app, ui, make_library, tmp_path, monkeypatch):
    monkeypatch.setattr(ui.gallery_tab, "GALLERY_PAGE_SIZE", 3)
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gestures(gallery.cards[0])[0](None)
    asyncio.run(gallery.on_next(None))
    press_ctrl(app)
    gestures(gallery.cards[0])[0](None)  # the 4th book, on page 2
    assert len(gallery.selection.ids) == 2
    assert gallery.count_text.value == "4 livro(s) · 2 selecionados"
    asyncio.run(gallery.on_prev(None))
    assert [card.selected for card in gallery.cards] == [True, False, False]


def test_clicking_a_book_gives_the_keyboard_focus_back(app, make_library, tmp_path):
    """Otherwise the focus stays in the search field after typing, and Shift/Ctrl
    pressed there are not heard by the window listener."""
    open_library(app, make_library, tmp_path)
    gestures(app.gallery.cards[1])[0](None)
    assert (app.keys.focus, ()) in app.page.tasks
