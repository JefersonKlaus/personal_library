"""Which modifier keys are held down right now (Flet click events do not say it)."""
from __future__ import annotations

from typing import Any

import flet as ft


# Flet names the keys after the physical key: "Shift Left", "Control Right", "Meta Left".
_MODIFIERS = ("shift", "control", "meta")  # Meta = Cmd on macOS (the Windows key elsewhere)


def _modifier(key: str | None) -> str | None:
    """'Control Left' -> 'control'; None for keys that are not modifiers."""
    name = (key or "").lower()
    return next((modifier for modifier in _MODIFIERS if modifier in name), None)


class ModifierKeys:
    """Tracks whether Shift and Ctrl are held, for Shift+click and Ctrl+click in the gallery.

    Flet's click events carry no modifier state, and page.on_keyboard_event only reports
    key presses, never releases. So the state comes from the key down/up events of a
    KeyboardListener around the whole window (`wrap`): it hears every key while the focus is
    anywhere inside the window content.

    A key released while something outside that content had the focus (another app, a
    dialog) would look stuck, so the state is also cleared when the window loses the focus
    (`on_window_event`) and whenever a key is pressed without it (`on_page_key`)."""

    def __init__(self) -> None:
        # "shift left", "control right"...: the left and right keys can both be down
        self._held: set[str] = set()
        self.listener: ft.KeyboardListener | None = None

    def _is_held(self, modifier: str) -> bool:
        return any(_modifier(key) == modifier for key in self._held)

    @property
    def shift(self) -> bool:
        return self._is_held("shift")

    @property
    def ctrl(self) -> bool:
        """Ctrl, or Cmd on macOS (there Ctrl+click is the right click)."""
        return self._is_held("control") or self._is_held("meta")

    def _release(self, modifier: str) -> None:
        self._held = {key for key in self._held if _modifier(key) != modifier}

    def wrap(self, content: ft.Control) -> ft.Control:
        """The window content inside the KeyboardListener.

        The expanding Container outside is what gives the content the window height:
        Flet does not apply `expand` to a KeyboardListener (it is not a layout control),
        and with the listener alone the content lost its height and the layout broke
        (header drawn over itself, series sidebar empty, status bar gone)."""
        self.listener = ft.KeyboardListener(
            content=content, autofocus=True,
            on_key_down=self.on_key_down, on_key_up=self.on_key_up)
        return ft.Container(expand=True, content=self.listener)

    async def focus(self) -> None:
        """Gives the keyboard focus back to the listener.

        Called when a book is clicked: otherwise the focus stays where it was (the search
        field, after typing in it) and Shift/Ctrl pressed there were not heard."""
        if self.listener is not None:
            await self.listener.focus()

    def on_key_down(self, event: Any) -> None:
        if _modifier(event.key):
            self._held.add(event.key.lower())

    def on_key_up(self, event: Any) -> None:
        if _modifier(event.key):
            self._held.discard(event.key.lower())

    def on_page_key(self, event: Any) -> None:
        """page.on_keyboard_event: a key pressed without a modifier means it is not held."""
        for modifier, held in (("shift", event.shift), ("control", event.ctrl),
                               ("meta", event.meta)):
            if not held:
                self._release(modifier)

    def on_window_event(self, event: Any) -> None:
        """page.window.on_event: a key may be released in another app after Alt+Tab."""
        if event.type == ft.WindowEventType.BLUR:
            self._held.clear()
