"""Ferramenta de linha de comando da biblioteca: adicionar, alterar, remover e criar.

Só o próprio programa da biblioteca pode alterá-la (ele mantém o banco de dados);
o app nunca escreve na pasta da biblioteca. Enquanto outro programa estiver usando
uma biblioteca, a ferramenta recusa o acesso (para não corromper o banco).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import BookEntry
from .location import is_library
from .manager import CLI_NAME, INSTALL_DIRS, LANGUAGE_ENV

_ADDED_IDS = re.compile(r"Added book ids?:\s*([\d,\s]+)", re.I)
LIBRARY_IN_USE = ("A biblioteca está sendo usada por outro programa (por exemplo, um "
                  "gerenciador ou leitor de e-books). Feche esse programa e tente de novo.")


@dataclass
class AddResult:
    """Resultado de adicionar um livro."""

    ok: bool
    book_ids: list[int] = field(default_factory=list)
    message: str = ""
    duplicate: bool = False  # a biblioteca já tinha um livro com o mesmo título e autor


def find_cli(custom: str | None = None) -> Path | None:
    """Procura o executável (caminho informado, PATH e pastas de instalação comuns)."""
    candidates: list[Path] = []
    if custom:
        given = Path(custom)
        candidates += [given] if given.is_file() else [given / f"{CLI_NAME}.exe", given / CLI_NAME]
    on_path = shutil.which(CLI_NAME)
    if on_path:
        candidates.append(Path(on_path))
    for folder in INSTALL_DIRS:
        candidates += [Path(folder) / f"{CLI_NAME}.exe", Path(folder) / CLI_NAME]
    return next((item for item in candidates if item.is_file()), None)


def add_command(executable: Path, library: Path, book_file: Path, entry: BookEntry,
                tags: list[str], cover: Path | None = None,
                allow_duplicate: bool = False) -> list[str]:
    """Monta o comando 'add'. Usa `--opção=valor` para que um título começando com '-'
    não seja confundido com uma opção."""
    command = [str(executable), "add", "--with-library", str(library)]
    if allow_duplicate:
        command.append("--duplicates")
    command += [f"--title={entry.title}", f"--authors={entry.author}"]
    if entry.series:
        command += [f"--series={entry.series}", f"--series-index={entry.series_index or 1:g}"]
    if entry.language:
        command.append(f"--languages={entry.language}")
    if tags:
        command.append(f"--tags={','.join(tags)}")
    if cover is not None:
        command.append(f"--cover={cover}")
    command.append(str(book_file))
    return command


def parse_added_ids(output: str) -> list[int]:
    """Lê os ids informados em 'Added book ids: 12, 13'."""
    match = _ADDED_IDS.search(output)
    return [int(item) for item in re.findall(r"\d+", match.group(1))] if match else []


def _error_message(output: str) -> str:
    """Mensagem para o usuário. Biblioteca em uso vira uma explicação clara, em vez da
    última linha (técnica, em inglês) da saída da ferramenta."""
    output = output.strip()
    if "running" in output.lower():
        return LIBRARY_IN_USE
    return output.splitlines()[-1] if output else "erro desconhecido"


class LibraryCli:
    """Executa a ferramenta de linha de comando da biblioteca."""

    def __init__(self, executable: Path, timeout: int = 300) -> None:
        self.executable = Path(executable)
        self.timeout = timeout

    @classmethod
    def find(cls, custom: str | None = None) -> "LibraryCli | None":
        executable = find_cli(custom)
        return cls(executable) if executable else None

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        # A ferramenta traduz as mensagens para o idioma do programa ("IDs de livro
        # adicionados: 12"); em inglês a leitura de "Added book ids" é confiável. Saída
        # decodificada com "replace": um título acentuado não pode derrubar a importação.
        env = {**os.environ, LANGUAGE_ENV: "en", "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=self.timeout, check=False,
                               creationflags=flags, env=env)

    def add_book(self, library: Path, book_file: Path, entry: BookEntry, tags: list[str],
                 cover: Path | None = None, allow_duplicate: bool = False) -> AddResult:
        """Adiciona um livro. Os metadados que não cabem na linha de comando (ordenação,
        data, editora) a ferramenta lê do OPF de mesmo nome ao lado de `book_file`."""
        command = add_command(self.executable, library, book_file, entry, tags, cover,
                              allow_duplicate)
        try:
            done = self._run(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return AddResult(False, message=f"não foi possível executar: {exc}")
        output = f"{done.stdout}\n{done.stderr}"
        ids = parse_added_ids(output)
        if done.returncode == 0 and ids:
            return AddResult(True, ids)
        if done.returncode == 0:
            return AddResult(False, message="já existe na biblioteca", duplicate=True)
        return AddResult(False, message=_error_message(output))

    def remove_books(self, library: Path, ids: list[int]) -> tuple[bool, str]:
        """Remove livros (vão para a lixeira da biblioteca). Devolve (ok, erro)."""
        if not ids:
            return True, ""
        command = [str(self.executable), "remove", "--with-library", str(library),
                   ",".join(str(book_id) for book_id in ids)]
        try:
            done = self._run(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"não foi possível executar: {exc}"
        return (True, "") if done.returncode == 0 else (
            False, _error_message(f"{done.stdout}\n{done.stderr}"))

    def set_fields(self, library: Path, book_id: int, fields: dict[str, str]) -> tuple[bool, str]:
        """Altera campos de um livro (ex.: {'title': ..., 'sort': ...}). Devolve (ok, erro).

        Mudar o título também renomeia a pasta do livro; quem faz isso é a ferramenta.
        """
        command = [str(self.executable), "set_metadata", "--with-library", str(library)]
        command += [f"--field={name}:{value}" for name, value in fields.items()]
        command.append(str(book_id))
        try:
            done = self._run(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"não foi possível executar: {exc}"
        return (True, "") if done.returncode == 0 else (
            False, _error_message(f"{done.stdout}\n{done.stderr}"))

    def create_library(self, path: Path | str) -> tuple[bool, str]:
        """Cria uma biblioteca vazia numa pasta vazia ou inexistente. Devolve (ok, erro).

        Quem cria é a própria ferramenta, então o banco sai no formato da versão instalada.
        """
        path = Path(path)
        if is_library(path):
            return True, ""
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            return False, f"{path} não está vazia; a biblioteca nova precisa de uma pasta vazia."
        created = not path.exists()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"não foi possível criar a pasta: {exc}"
        try:
            done = self._run([str(self.executable), "--with-library", str(path), "list"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = f"não foi possível executar: {exc}"
        else:
            if done.returncode == 0 and is_library(path):
                return True, ""
            error = _error_message(f"{done.stdout}\n{done.stderr}")
        if created:  # não deixa para trás a pasta que o app criou
            shutil.rmtree(path, ignore_errors=True)
        return False, error
