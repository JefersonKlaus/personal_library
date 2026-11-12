"""Personal Library. Abre o app:  flet run   (ou  python main.py)"""
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
    # no_cdn: no modo web (`flet run --web`) os arquivos do Flet saem do próprio app,
    # sem buscar nada na internet; no desktop não muda nada.
    ft.run(main, no_cdn=True)
    return 0


if __name__ == "__main__":
    sys.exit(run())
