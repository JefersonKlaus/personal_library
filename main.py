"""Personal Library. Opens the app:  flet run   (or  python main.py)"""
import sys


def run() -> int:
    try:
        import flet as ft
    except ImportError:
        print("Flet não está instalado. Rode:  pip install -r requirements.txt")
        return 1

    from src.core.logging_setup import setup_logging
    from src.ui.app import main

    setup_logging()
    # no_cdn: in web mode (`flet run --web`) the Flet files are served by the app
    # itself, with nothing fetched from the internet; on desktop it changes nothing.
    ft.run(main, no_cdn=True)
    return 0


if __name__ == "__main__":
    sys.exit(run())
