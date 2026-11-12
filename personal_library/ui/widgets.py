"""Peças de interface reutilizadas pelas abas."""
from __future__ import annotations

import flet as ft

from ..models import Status

TAB_IMPORT, TAB_GALLERY, TAB_EXPORT = range(3)  # ordem das abas na janela

STATUS_COLORS = {
    Status.READY: ft.Colors.GREEN_700,
    Status.WARNING: ft.Colors.ORANGE_700,
    Status.DUPLICATE: ft.Colors.GREY_600,
    Status.EXISTS: ft.Colors.GREY_600,
    Status.ERROR: ft.Colors.RED_700,
    Status.DONE: ft.Colors.BLUE_700,
    Status.FAILED: ft.Colors.RED_700,
}


def format_size(size: int) -> str:
    """12345678 -> '11,8 MB'."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            text = f"{value:.0f}" if unit == "B" else f"{value:.1f}".replace(".", ",")
            return f"{text} {unit}"
        value /= 1024
    return f"{size} B"


def section(title: str, *controls: ft.Control, expand: bool = False) -> ft.Container:
    """Bloco com título, usado para agrupar cada etapa da tela."""
    return ft.Container(
        content=ft.Column(controls=[ft.Text(title, weight=ft.FontWeight.BOLD), *controls],
                          spacing=8, expand=expand,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=12, bgcolor=ft.Colors.BLUE_GREY_50, border_radius=8, expand=expand)


def option_grid(*controls: ft.Control) -> ft.ResponsiveRow:
    """Opções lado a lado (Row com wrap empilha as caixas no Flet 1.0)."""
    return ft.ResponsiveRow(
        controls=[ft.Container(content=c, col={"xs": 12, "md": 6, "lg": 3}) for c in controls],
        spacing=4, run_spacing=0)


def pager_controls(on_prev, on_next) -> tuple[ft.OutlinedButton, ft.Text, ft.OutlinedButton]:
    return (ft.OutlinedButton("Anterior", on_click=on_prev, disabled=True), ft.Text(size=12),
            ft.OutlinedButton("Próxima", on_click=on_next, disabled=True))


def update_pager(prev: ft.Control, label: ft.Text, next_: ft.Control, index: int,
                 pages: int) -> None:
    """Mostra 'Página x de y' e só exibe os botões quando há mais de uma página."""
    label.value = f"Página {index + 1} de {pages}"
    prev.disabled, next_.disabled = index == 0, index >= pages - 1
    for control in (prev, label, next_):
        control.visible = pages > 1


def page_count(total: int, size: int) -> int:
    return max(1, -(-total // size))
