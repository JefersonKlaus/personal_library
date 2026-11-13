"""A card of the gallery: clicks (no delay), double click, right-button menu."""
from helpers import open_library


def test_left_click_is_not_delayed_by_double_click_detection(app, make_library, tmp_path):
    """With on_double_tap on the GestureDetector, Flutter delays every left click
    (~300 ms) waiting for a second one. The card selects on on_tap_down and detects the
    double click by itself, so the left button is as immediate as the right one."""
    open_library(app, make_library, tmp_path)
    for card in app.gallery.cards:
        detector = card.control.content
        assert getattr(detector, "on_double_tap", None) is None
        assert getattr(detector, "on_tap", None) is None
        assert detector.on_tap_down is not None


def test_slow_clicks_do_not_open_and_triple_click_opens_once(app, ui, make_library, tmp_path,
                                                             monkeypatch):
    open_library(app, make_library, tmp_path)
    card = app.gallery.cards[0]
    clock = [100.0]
    monkeypatch.setattr(ui.book_views.time, "monotonic", lambda: clock[0])
    tap = card.control.content.on_tap_down
    tap(None)
    clock[0] += ui.book_views.DOUBLE_CLICK_SECONDS + 0.1  # too slow
    tap(None)
    assert card.selected and app.page.dialogs == []
    clock[0] += 0.1
    tap(None)  # now yes: a double click
    assert len(app.page.dialogs) == 1
    clock[0] += 0.1
    tap(None)  # third quick click: only selects, does not open another window
    assert len(app.page.dialogs) == 1


def test_quick_clicks_on_two_different_cards_do_not_open(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    first, second = app.gallery.cards[0], app.gallery.cards[1]
    first.control.content.on_tap_down(None)
    second.control.content.on_tap_down(None)
    assert second.selected and not first.selected and app.page.dialogs == []


def test_right_button_menu_has_edit_metadata(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    items = [item.content for item in app.gallery.cards[0].control.secondary_items]
    assert items == ["Abrir", "Editar metadados"]
