"""Personal Library. Abre o app desktop:  python main.py"""
import sys


def run() -> int:
    try:
        import flet as ft
    except ImportError:
        print("Flet não está instalado. Rode:  pip install -r requirements.txt")
        return 1

    from pdf2calibre.app_logging import setup_logging
    from pdf2calibre.ui import main

    setup_logging()
    ft.run(main)
    return 0


if __name__ == "__main__":
    sys.exit(run())
