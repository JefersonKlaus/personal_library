"""Interface Flet: escolher PDFs, revisar título/autor e organizar para o Calibre."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import queue
import threading
from pathlib import Path
from typing import Any, Callable

import flet as ft

from . import calibre, organizer, planner
from .models import BookEntry, Mode, Options, Status
from .settings import Settings, load_settings, save_settings

logger = logging.getLogger(__name__)

PAGE_SIZE = 40
MAX_LOG_LINES = 400
LOCKED_STATUSES = (Status.ERROR, Status.DONE, Status.FAILED)

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


class OrganizerApp:
    """Monta a tela e liga os botões às funções de pdf2calibre."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.settings: Settings = load_settings()
        self.options: Options = self.settings.get_options()
        self.sources: list[Path] = [Path(p) for p in self.settings.last_sources if Path(p).exists()]
        self.entries: list[BookEntry] = []
        self.page_index = 0
        self.cancel_event = threading.Event()
        self._build_controls()

    # ------------------------------------------------------------------ montagem

    def _build_controls(self) -> None:
        opts = self.options
        self.file_picker = ft.FilePicker()

        self.source_label = ft.Text(size=12, color=ft.Colors.GREY_700)
        self.source_input = ft.TextField(
            label="Colar o caminho de uma pasta ou de um PDF", dense=True, expand=True,
            on_submit=self.on_add_typed)
        self.dest_field = ft.TextField(
            label="Pasta de destino (onde os livros organizados serão criados)",
            value=self.settings.destination, dense=True, expand=True)

        self.cb_recursive = ft.Checkbox(label="Incluir subpastas", value=opts.recursive)
        self.cb_folder = ft.Checkbox(
            label="Uma pasta por livro (Autor/Título)", value=opts.folder_per_book)
        self.cb_opf = ft.Checkbox(label="Gerar metadata.opf", value=opts.write_opf)
        self.cb_cover = ft.Checkbox(
            label="Extrair capa (precisa de pypdfium2 e Pillow)", value=opts.extract_cover)
        self.cb_dupes = ft.Checkbox(label="Ignorar arquivos idênticos", value=opts.skip_duplicates)
        self.cb_pdf_meta = ft.Checkbox(
            label="Preferir metadados de dentro do PDF", value=opts.prefer_pdf_metadata)
        self.cb_author_first = ft.Checkbox(
            label="Nome do arquivo é 'Autor - Título'", value=opts.author_first)
        self.sw_move = ft.Switch(
            label="Mover em vez de copiar (apaga o original depois de verificar)",
            value=opts.mode is Mode.MOVE)
        self.tags_field = ft.TextField(
            label="Etiquetas para todos os livros (separadas por vírgula)",
            value=", ".join(opts.tags), dense=True, expand=True)

        self.cb_calibre = ft.Checkbox(
            label="Importar no Calibre com calibredb (feche o Calibre antes)",
            value=self.settings.use_calibredb)
        self.library_field = ft.TextField(
            label="Biblioteca do Calibre (pasta com metadata.db)",
            value=self.settings.library, dense=True, expand=True,
            on_change=self.on_calibre_change)
        self.calibredb_field = ft.TextField(
            label="Caminho do calibredb (opcional)", value=self.settings.calibredb,
            dense=True, expand=True, on_change=self.on_calibre_change)
        self.calibre_status = ft.Text(size=12)

        self.btn_scan = ft.Button("Analisar", icon=ft.Icons.SEARCH, on_click=self.on_scan)
        self.btn_dry = ft.OutlinedButton("Simular", on_click=self.on_dry_run)
        self.btn_run = ft.Button("Organizar", icon=ft.Icons.PLAY_ARROW, on_click=self.on_run)
        self.btn_cancel = ft.OutlinedButton("Cancelar", on_click=self.on_cancel, disabled=True)
        self.btn_undo = ft.OutlinedButton("Desfazer última", icon=ft.Icons.UNDO, on_click=self.on_undo)
        self.action_buttons = [self.btn_scan, self.btn_dry, self.btn_run, self.btn_undo]

        self.progress = ft.ProgressBar(value=0)
        self.status_text = ft.Text(size=12)
        self.summary_text = ft.Text(weight=ft.FontWeight.BOLD)
        self.list_view = ft.ListView(controls=[], spacing=6, height=380)
        self.prev_btn = ft.OutlinedButton("Anterior", on_click=self.on_prev, disabled=True)
        self.next_btn = ft.OutlinedButton("Próxima", on_click=self.on_next, disabled=True)
        self.page_label = ft.Text(size=12)
        self.log_view = ft.ListView(controls=[], spacing=0, height=130, auto_scroll=True)

    def build(self) -> None:
        """Registra o seletor de arquivos e coloca todos os controles na página."""
        registry = getattr(self.page, "services", None)
        if registry is None:  # versões antigas do Flet usam overlay
            registry = self.page.overlay
        registry.append(self.file_picker)

        pick_row = ft.Row(controls=[
            ft.Button("Adicionar PDFs…", icon=ft.Icons.PICTURE_AS_PDF, on_click=self.on_pick_files),
            ft.Button("Adicionar pasta…", icon=ft.Icons.FOLDER_OPEN, on_click=self.on_pick_folder),
            ft.OutlinedButton("Limpar", on_click=self.on_clear),
        ], wrap=True, spacing=8)
        typed_row = ft.Row(controls=[
            self.source_input, ft.OutlinedButton("Adicionar", on_click=self.on_add_typed)])
        dest_row = ft.Row(controls=[
            self.dest_field, ft.OutlinedButton("Escolher…", on_click=self.on_pick_destination)])
        library_row = ft.Row(controls=[
            self.library_field, ft.OutlinedButton("Escolher…", on_click=self.on_pick_library)])
        options_row = ft.Row(controls=[
            self.cb_recursive, self.cb_folder, self.cb_opf, self.cb_cover,
            self.cb_dupes, self.cb_pdf_meta, self.cb_author_first], wrap=True, spacing=12)
        actions = ft.Row(controls=[*self.action_buttons[:3], self.btn_cancel, self.btn_undo],
                         wrap=True, spacing=8)
        pager = ft.Row(controls=[self.prev_btn, self.page_label, self.next_btn], spacing=12)

        self.page.add(ft.Column(controls=[
            ft.Text("PDF → Calibre", size=26, weight=ft.FontWeight.BOLD),
            ft.Text("Organize um lote de PDFs em pastas Autor/Título com metadados "
                    "prontos para o Calibre.", size=13, color=ft.Colors.GREY_700),
            self._card("1. Origem", pick_row, typed_row, self.source_label),
            self._card("2. Destino e opções", dest_row, options_row, self.sw_move, self.tags_field),
            self._card("3. Calibre (opcional)", self.cb_calibre, library_row,
                       self.calibredb_field, self.calibre_status),
            self._card("4. Revisar e organizar", actions, self.progress, self.status_text,
                       self.summary_text, self.list_view, pager),
            self._card("Registro", self.log_view),
        ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True))
        self._update_sources_label()
        self._update_calibre_status()
        self.page.update()

    @staticmethod
    def _card(title: str, *controls: ft.Control) -> ft.Container:
        return ft.Container(
            content=ft.Column(controls=[ft.Text(title, weight=ft.FontWeight.BOLD), *controls],
                              spacing=8),
            padding=12, bgcolor=ft.Colors.BLUE_GREY_50, border_radius=8)

    # ------------------------------------------------------------------ estado

    def _collect_options(self, dry_run: bool = False) -> Options:
        tags = [tag.strip() for tag in (self.tags_field.value or "").split(",") if tag.strip()]
        self.options = dataclasses.replace(
            self.options,
            recursive=bool(self.cb_recursive.value),
            folder_per_book=bool(self.cb_folder.value),
            write_opf=bool(self.cb_opf.value),
            extract_cover=bool(self.cb_cover.value),
            skip_duplicates=bool(self.cb_dupes.value),
            prefer_pdf_metadata=bool(self.cb_pdf_meta.value),
            author_first=bool(self.cb_author_first.value),
            mode=Mode.MOVE if self.sw_move.value else Mode.COPY,
            tags=tags,
            dry_run=dry_run,
        )
        return self.options

    def _save(self) -> None:
        self.settings.destination = (self.dest_field.value or "").strip()
        self.settings.library = (self.library_field.value or "").strip()
        self.settings.calibredb = (self.calibredb_field.value or "").strip()
        self.settings.use_calibredb = bool(self.cb_calibre.value)
        self.settings.last_sources = [str(path) for path in self.sources]
        self.settings.set_options(dataclasses.replace(self.options, dry_run=False))
        save_settings(self.settings)

    def _log(self, message: str, error: bool = False) -> None:
        logger.info(message)
        color = ft.Colors.RED_700 if error else None
        self.log_view.controls.append(ft.Text(message, size=12, color=color, selectable=True))
        del self.log_view.controls[:-MAX_LOG_LINES]
        self.page.update()

    def _set_busy(self, busy: bool) -> None:
        for button in self.action_buttons:
            button.disabled = busy
        self.btn_cancel.disabled = not busy
        if not busy:
            self.progress.value = 0
        self.page.update()

    def _update_sources_label(self) -> None:
        if not self.sources:
            self.source_label.value = "Nenhuma origem escolhida."
        else:
            names = ", ".join(path.name or str(path) for path in self.sources[:4])
            extra = f" e mais {len(self.sources) - 4}" if len(self.sources) > 4 else ""
            self.source_label.value = f"{len(self.sources)} origem(ns): {names}{extra}"

    def _update_calibre_status(self) -> None:
        found = calibre.find_calibredb((self.calibredb_field.value or "").strip() or None)
        library = (self.library_field.value or "").strip()
        parts = [f"calibredb: {found}" if found else "calibredb não encontrado (instale o Calibre)"]
        if library:
            ok = calibre.is_calibre_library(library)
            parts.append("biblioteca válida" if ok else "metadata.db não encontrado nessa pasta")
        self.calibre_status.value = " · ".join(parts)
        self.calibre_status.color = ft.Colors.GREEN_700 if found else ft.Colors.ORANGE_700

    def _add_sources(self, paths: list[Path]) -> None:
        for path in paths:
            if path not in self.sources:
                self.sources.append(path)
        self._update_sources_label()
        self._save()
        self.page.update()

    # ------------------------------------------------------------------ lista

    def _row(self, entry: BookEntry) -> ft.Control:
        checkbox = ft.Checkbox(
            value=entry.selected, disabled=entry.status in LOCKED_STATUSES,
            on_change=lambda e, item=entry: self._toggle(item, bool(e.control.value)))
        title = ft.TextField(
            label="Título", value=entry.title, dense=True, expand=3,
            on_change=lambda e, item=entry: self._edit(item, "title", e.control.value))
        author = ft.TextField(
            label="Autor(es), separe com &", value=entry.author, dense=True, expand=2,
            on_change=lambda e, item=entry: self._edit(item, "author", e.control.value))
        status = ft.Text(entry.status.value, color=STATUS_COLORS[entry.status],
                         weight=ft.FontWeight.BOLD, width=84)
        detail = f"{entry.source.name} · {entry.pages} pág. · {format_size(entry.size)}"
        if entry.notes:
            detail += " · " + "; ".join(entry.notes)
        return ft.Column(controls=[
            ft.Row(controls=[checkbox, title, author, status],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Text(detail, size=11, color=ft.Colors.GREY_600),
        ], spacing=0)

    @staticmethod
    def _toggle(entry: BookEntry, value: bool) -> None:
        entry.selected = value
        if value and entry.status in (Status.DUPLICATE, Status.EXISTS):
            entry.status = Status.READY  # o usuário quer este mesmo assim

    @staticmethod
    def _edit(entry: BookEntry, field: str, value: str | None) -> None:
        setattr(entry, field, (value or "").strip())
        setattr(entry, f"{field}_origin", "manual")

    def _page_count(self) -> int:
        return max(1, -(-len(self.entries) // PAGE_SIZE))

    def _refresh_list(self) -> None:
        start = self.page_index * PAGE_SIZE
        self.list_view.controls = [self._row(item) for item in self.entries[start:start + PAGE_SIZE]]
        pages = self._page_count()
        self.page_label.value = f"Página {self.page_index + 1} de {pages}" if self.entries else ""
        self.prev_btn.disabled = self.page_index == 0
        self.next_btn.disabled = self.page_index >= pages - 1
        counts = planner.summarize(self.entries)
        self.summary_text.value = (
            "  ·  ".join(f"{status.value}: {n}" for status, n in counts.items())
            if self.entries else "")
        self.page.update()

    def on_prev(self, _event: Any) -> None:
        self.page_index = max(0, self.page_index - 1)
        self._refresh_list()

    def on_next(self, _event: Any) -> None:
        self.page_index = min(self._page_count() - 1, self.page_index + 1)
        self._refresh_list()

    # ------------------------------------------------------------------ origem/destino

    async def on_pick_files(self, _event: Any) -> None:
        try:
            files = await self.file_picker.pick_files(
                dialog_title="Escolha os PDFs", allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])
        except Exception as exc:
            self._log(f"Seletor de arquivos indisponível ({exc}). Cole o caminho no campo.", True)
            return
        self._add_sources([Path(f.path) for f in files or [] if getattr(f, "path", None)])

    async def on_pick_folder(self, _event: Any) -> None:
        folder = await self._pick_directory("Escolha a pasta com os PDFs")
        if folder:
            self._add_sources([Path(folder)])

    async def on_pick_destination(self, _event: Any) -> None:
        folder = await self._pick_directory("Escolha a pasta de destino")
        if folder:
            self.dest_field.value = folder
            self._save()
            self.page.update()

    async def on_pick_library(self, _event: Any) -> None:
        folder = await self._pick_directory("Escolha a biblioteca do Calibre")
        if folder:
            self.library_field.value = folder
            self.on_calibre_change(None)

    async def _pick_directory(self, title: str) -> str | None:
        try:
            return await self.file_picker.get_directory_path(dialog_title=title)
        except Exception as exc:
            self._log(f"Seletor de pastas indisponível ({exc}). Cole o caminho no campo.", True)
            return None

    def on_add_typed(self, _event: Any) -> None:
        text = (self.source_input.value or "").strip().strip('"')
        if not text:
            return
        path = Path(text).expanduser()
        if not path.exists():
            self._log(f"Caminho não encontrado: {text}", True)
            return
        self.source_input.value = ""
        self._add_sources([path])

    def on_clear(self, _event: Any) -> None:
        self.sources.clear()
        self.entries.clear()
        self.page_index = 0
        self._update_sources_label()
        self._refresh_list()
        self._save()

    def on_calibre_change(self, _event: Any) -> None:
        self._update_calibre_status()
        self.page.update()

    def on_cancel(self, _event: Any) -> None:
        self.cancel_event.set()
        self.status_text.value = "Cancelando…"
        self.page.update()

    # ------------------------------------------------------------------ execução

    def _drain(self, updates: "queue.Queue[tuple[int, int, str]]", label: str) -> None:
        latest = None
        while True:
            try:
                latest = updates.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return
        done, total, message = latest
        self.progress.value = done / total if total else None
        self.status_text.value = f"{label}: {done}/{total} — {message}"
        self.page.update()

    async def _run_job(self, func: Callable[..., Any], *args: Any, label: str,
                       cancellable: bool = True) -> Any:
        """Roda `func` em outra thread mostrando o progresso, sem travar a janela."""
        updates: "queue.Queue[tuple[int, int, str]]" = queue.Queue()
        kwargs: dict[str, Any] = {"progress": lambda d, t, m: updates.put((d, t, m))}
        if cancellable:
            kwargs["cancel"] = self.cancel_event
        self.cancel_event.clear()
        self._set_busy(True)
        task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
        try:
            while not task.done():
                self._drain(updates, label)
                await asyncio.sleep(0.1)
            self._drain(updates, label)
            return task.result()
        finally:
            self._set_busy(False)
            self.status_text.value = ""
            self.page.update()

    async def on_scan(self, _event: Any) -> None:
        if not self.sources:
            self._log("Escolha ao menos uma pasta ou PDF na origem.", True)
            return
        options = self._collect_options()
        dest = (self.dest_field.value or "").strip()
        exclude = Path(dest) if dest else None
        self._save()
        try:
            files = await asyncio.to_thread(planner.find_pdfs, self.sources, options.recursive, exclude)
            if not files:
                self._log("Nenhum PDF encontrado nas origens escolhidas.", True)
                return
            self._log(f"{len(files)} PDF(s) encontrados. Lendo metadados…")
            entries = await self._run_job(
                planner.build_entries, files, options, label="Analisando")
        except Exception as exc:
            logger.exception("Falha na análise")
            self._log(f"Erro na análise: {exc}", True)
            return
        duplicates = planner.mark_duplicates(entries, options)
        self.entries, self.page_index = entries, 0
        self._log(f"Análise concluída: {len(entries)} arquivo(s), {duplicates} duplicado(s).")
        self._refresh_list()

    async def on_dry_run(self, _event: Any) -> None:
        await self._organize(dry_run=True)

    async def on_run(self, _event: Any) -> None:
        await self._organize(dry_run=False)

    async def _organize(self, dry_run: bool) -> None:
        if not self.entries:
            self._log("Analise os PDFs antes de organizar.", True)
            return
        dest = (self.dest_field.value or "").strip()
        if not dest:
            self._log("Informe a pasta de destino.", True)
            return
        options = self._collect_options(dry_run)
        self._save()
        try:
            await asyncio.to_thread(planner.assign_targets, self.entries, Path(dest), options)
            if options.mode is Mode.MOVE and not dry_run:
                self._log("Modo mover: cada original só é apagado depois da cópia ser verificada.")
            report = await self._run_job(
                organizer.organize, self.entries, Path(dest), options,
                label="Simulando" if dry_run else "Organizando")
        except Exception as exc:
            logger.exception("Falha ao organizar")
            self._log(f"Erro ao organizar: {exc}", True)
            return
        self._log(report.summary())
        for error in report.errors[:20]:
            self._log(f"  ✗ {error}", True)
        if report.manifest:
            self._log(f"Registro para desfazer: {report.manifest}")
        self._refresh_list()
        if not dry_run and self.cb_calibre.value:
            await self._import_into_calibre(options)

    async def _import_into_calibre(self, options: Options) -> None:
        library = (self.library_field.value or "").strip()
        tool = calibre.find_calibredb((self.calibredb_field.value or "").strip() or None)
        if tool is None:
            self._log("calibredb não encontrado; a importação no Calibre foi pulada.", True)
            return
        if not calibre.is_calibre_library(library):
            self._log("A pasta da biblioteca não tem metadata.db; importação pulada.", True)
            return
        done = [item for item in self.entries if item.status is Status.DONE]
        try:
            results = await self._run_job(
                calibre.import_entries, done, Path(library), options, tool,
                label="Importando no Calibre")
        except Exception as exc:
            logger.exception("Falha na importação")
            self._log(f"Erro na importação: {exc}", True)
            return
        added = sum(1 for item in results if item.ok)
        self._log(f"Calibre: {added} livro(s) adicionados, {len(results) - added} não adicionados.")
        for item in results:
            if not item.ok:
                self._log(f"  ✗ {item.entry.title}: {item.message}", True)

    async def on_undo(self, _event: Any) -> None:
        dest = (self.dest_field.value or "").strip()
        manifest = organizer.latest_manifest(Path(dest)) if dest else None
        if manifest is None:
            self._log("Não há nada para desfazer neste destino.", True)
            return
        try:
            report = await self._run_job(
                organizer.undo, manifest, label="Desfazendo", cancellable=False)
        except Exception as exc:
            logger.exception("Falha ao desfazer")
            self._log(f"Erro ao desfazer: {exc}", True)
            return
        self._log(f"Desfeito: {report.done} de {report.total} livros.")
        for error in report.errors[:20]:
            self._log(f"  ✗ {error}", True)
        self.entries.clear()
        self._refresh_list()


async def main(page: ft.Page) -> None:
    """Ponto de entrada passado para `ft.run`."""
    page.title = "PDF → Calibre"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 16
    try:
        page.window.width = 1100
        page.window.height = 860
    except Exception:  # janela não configurável (web/mobile): sem problema
        logger.debug("window não configurável", exc_info=True)
    OrganizerApp(page).build()
