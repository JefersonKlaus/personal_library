"""Shift and Ctrl held? (the window keyboard listener)."""
import asyncio
from types import SimpleNamespace

from helpers import page_key, press_ctrl, press_shift


def test_both_shift_keys_and_stuck_shift_protection(app, ui):
    keys = app.keys
    press_shift(app, key="Shift Left")
    press_shift(app, key="Shift Right")
    press_shift(app, down=False, key="Shift Left")
    assert keys.shift  # the right one is still down
    press_shift(app, down=False, key="Shift Right")
    assert not keys.shift
    press_shift(app, key="A")  # other keys do not count
    assert not keys.shift
    # Released while another app had the focus: cleared when the window loses the focus...
    press_shift(app)
    keys.on_window_event(SimpleNamespace(type=ui.keyboard.ft.WindowEventType.FOCUS))
    assert keys.shift
    keys.on_window_event(SimpleNamespace(type=ui.keyboard.ft.WindowEventType.BLUR))
    assert not keys.shift
    # ...or as soon as a key is pressed without Shift (page.on_keyboard_event).
    press_shift(app)
    keys.on_page_key(page_key("Shift Left", shift=True))
    assert keys.shift
    keys.on_page_key(page_key("B"))
    assert not keys.shift


def test_ctrl_and_cmd_keys_are_tracked_apart_from_shift(app, ui):
    keys = app.keys
    press_ctrl(app)
    assert keys.ctrl and not keys.shift
    press_shift(app)
    assert keys.ctrl and keys.shift
    press_ctrl(app, down=False)
    assert not keys.ctrl and keys.shift  # releasing Ctrl keeps Shift
    press_shift(app, down=False)
    press_ctrl(app, key="Meta Left")  # Cmd on macOS
    assert keys.ctrl
    press_ctrl(app, down=False, key="Meta Left")
    assert not keys.ctrl
    # Stuck protection, per key: a key pressed with Shift but without Ctrl clears only Ctrl.
    press_ctrl(app, key="Control Right")
    press_shift(app)
    keys.on_page_key(page_key("A", shift=True))
    assert keys.shift and not keys.ctrl
    press_ctrl(app, key="Meta Right")
    keys.on_page_key(page_key("A", shift=True, meta=True))
    assert keys.ctrl  # Cmd is still down
    keys.on_window_event(SimpleNamespace(type=ui.keyboard.ft.WindowEventType.BLUR))
    assert not keys.ctrl and not keys.shift


def test_the_window_listens_to_the_keyboard(app, ui):
    """Shift is only heard inside a KeyboardListener with the focus, around everything.

    The listener sits inside an expanding Container: Flet does not apply `expand` to a
    KeyboardListener, and with the listener as the root the layout lost the window height
    (header drawn over itself, series sidebar empty, status bar gone)."""
    [root] = app.page.added
    assert root.expand and not hasattr(root, "on_key_down")  # the layout control
    listener = root.content
    assert listener.on_key_down == app.keys.on_key_down
    assert listener.on_key_up == app.keys.on_key_up
    assert listener.autofocus and not getattr(listener, "expand", False)
    assert listener.content.expand and listener.content.controls[1] is app.tabs
    assert app.page.on_keyboard_event == app.on_page_key  # -> keys, and the reader if open
    assert app.page.window.on_event == app.keys.on_window_event


def test_focus_asks_the_window_listener(app):
    calls = []

    async def focus():
        calls.append("focus")

    app.keys.listener.focus = focus
    asyncio.run(app.keys.focus())
    assert calls == ["focus"]
