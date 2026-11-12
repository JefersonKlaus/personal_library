"""Como importar: o padrão do nome dos arquivos e os valores fixos.

Exemplo: "@name - @vol - @auth" ou "@name - @vol; @auth=ONE".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .filename_parser import ParsedName, automatic_values, compose
from ..core.text import extract_year, normalize_text, strip_noise
from .volumes import VOL_NUMBER, VOL_TRAILING, VOL_WORD, match_volume


class PatternError(ValueError):
    """Configuração de importação inválida (mensagem pronta para mostrar)."""


# Parâmetros aceitos (@nome) e o campo que cada um preenche.
PARAMETERS = {
    "name": "title", "nome": "title", "title": "title", "titulo": "title", "título": "title",
    "vol": "volume", "volume": "volume",
    "auth": "author", "author": "author", "autor": "author", "autores": "author",
    "year": "year", "ano": "year",
    "series": "series", "serie": "series", "série": "series",
    "publisher": "publisher", "editora": "publisher",
    "lang": "language", "language": "language", "idioma": "language",
    "tags": "tags", "etiquetas": "tags",
    "skip": "skip", "ignore": "skip", "ignorar": "skip",
}
FIELD_LABELS = {
    "title": "Título", "author": "Autor", "volume": "Volume", "year": "Ano", "series": "Série",
    "publisher": "Editora", "language": "Idioma", "tags": "Etiquetas",
}
_LEGACY = {"NOME": "@name", "NAME": "@name", "TITULO": "@name", "TÍTULO": "@name",
           "TITLE": "@name", "VOL": "@vol", "VOLUME": "@vol", "AUTOR": "@auth",
           "AUTORES": "@auth", "AUTH": "@auth", "AUTHOR": "@auth", "ANO": "@year",
           "YEAR": "@year", "SERIE": "@series", "SÉRIE": "@series", "SERIES": "@series",
           "IGNORAR": "@skip", "*": "@skip"}
_PARAM = re.compile(r"@([^\W\d_]+)(?:\s*=\s*(?P<value>.*?)(?=\s+@|\s*;|$))?", re.UNICODE)
_FIELD_REGEX = {
    "volume": rf"(?:{VOL_WORD}\.?\s*|v\.?\s*(?=\d))?{VOL_NUMBER}",
    "year": r"\(?(?:1[5-9]|20)\d{2}\)?",
}
PATTERN_HELP = (
    "Parâmetros: @name (título), @vol (volume), @auth (autor), @year (ano), @series (série), "
    "@publisher (editora), @lang (idioma), @tags (etiquetas) e @skip (ignorar).\n"
    "Escreva-os na ordem do nome do arquivo, com os delimitadores usados: @name - @vol - @auth.\n"
    "Valor fixo para todos os PDFs: @auth=ONE (no fim ou depois de ;), ex.: "
    "@name - @vol; @auth=ONE; @tags=mangá.\n"
    "Partes que faltam no fim do nome ficam vazias. Vazio = automático.")


@dataclass
class ImportSpec:
    """O que o usuário escreveu em "Como importar": padrão do nome e valores fixos.

    `fields[i]` é o campo da i-ésima parte do nome; `separators[i]` é o texto
    (delimitador) antes dela, e o último separador sobra no fim.
    """

    text: str
    fields: list[str] = field(default_factory=list)
    separators: list[str] = field(default_factory=list)
    fixed: dict[str, str] = field(default_factory=dict)

    @property
    def has_pattern(self) -> bool:
        return bool(self.fields)

    def _separator_regex(self, literal: str, strict: bool, edge: bool) -> str:
        core = literal.strip()
        if not core:
            return "" if edge else r"\s+"
        chars = "".join("[-–—]" if char in "-–—" else re.escape(char) for char in core)
        if edge:
            return rf"\s*{chars}\s*"
        return rf"\s+{chars}\s+" if strict else rf"\s*{chars}\s*"

    def regex(self, count: int, strict: bool) -> re.Pattern:
        """Regex com as `count` primeiras partes (as do fim podem faltar no arquivo)."""
        pieces = ["^", self._separator_regex(self.separators[0], strict, edge=True)]
        for index in range(count):
            if index:
                pieces.append(self._separator_regex(self.separators[index], strict, edge=False))
            pieces.append(f"(?P<p{index}>{_FIELD_REGEX.get(self.fields[index], '.+?')})")
        if count == len(self.fields):
            pieces.append(self._separator_regex(self.separators[-1], strict, edge=True))
        pieces.append("$")
        return re.compile("".join(pieces), re.I)


def _legacy_to_parameters(text: str) -> str:
    """'NOME - VOL - AUTOR' (versão anterior) -> '@name - @vol - @auth'."""
    return re.sub(r"\*|[^\W\d_]+",
                  lambda m: _LEGACY.get(m.group(0).upper(), m.group(0))
                  if m.group(0).isupper() or m.group(0) == "*" else m.group(0), text)


def _check_fixed(field_name: str, value: str) -> str:
    value = value.strip().strip('"').strip("'").strip()
    if not value:
        raise PatternError(f"Falta o valor em @{_param_name(field_name)}=.")
    if field_name == "skip":
        raise PatternError("@skip não tem valor fixo.")
    if field_name == "volume" and match_volume(value, bare_digits=4) is None:
        raise PatternError(f"Volume fixo inválido: {value!r} (ex.: @vol=3).")
    if field_name == "year" and not re.fullmatch(r"\(?(?:1[5-9]|20)\d{2}\)?", value):
        raise PatternError(f"Ano fixo inválido: {value!r} (ex.: @year=1999).")
    return value


def _param_name(field_name: str) -> str:
    return {"title": "name", "volume": "vol", "author": "auth", "language": "lang"}.get(
        field_name, field_name)


def compile_spec(text: str) -> ImportSpec | None:
    """Interpreta "Como importar"; vazio = automático (None). Levanta PatternError."""
    text = normalize_text(text or "")
    if not text:
        return None
    if "@" not in text:
        text = _legacy_to_parameters(text)
        if "@" not in text:
            raise PatternError("Use parâmetros com @, ex.: @name - @vol - @auth.")
    spec = ImportSpec(text)
    pattern_done = False
    for segment in text.split(";"):
        params = list(_PARAM.finditer(segment))
        for match in params:
            if match.group(1).lower() not in PARAMETERS:
                known = ", ".join(f"@{n}" for n in ("name", "vol", "auth", "year", "series",
                                                     "publisher", "lang", "tags", "skip"))
                raise PatternError(f"Parâmetro desconhecido: @{match.group(1)} (use {known}).")
        leftover = _PARAM.sub("", segment).strip()
        only_fixed = all(m.group("value") is not None for m in params) and not leftover
        if not segment.strip():
            continue
        if only_fixed:
            for match in params:
                name = PARAMETERS[match.group(1).lower()]
                spec.fixed[name] = _check_fixed(name, match.group("value"))
            continue
        if pattern_done:
            raise PatternError("Só pode haver um padrão de nome. Separe os valores fixos "
                               "(@auth=...) com ponto e vírgula.")
        pattern_done = True
        literal, position = "", 0
        for match in params:
            name = PARAMETERS[match.group(1).lower()]
            separator = literal + segment[position:match.start()]
            if spec.fields and not separator:
                raise PatternError("Separe os parâmetros com o delimitador do nome do arquivo "
                                   "(ex.: @name - @auth).")
            spec.separators.append(separator)
            spec.fields.append(name)
            if match.group("value") is not None:  # "@auth=ONE" no meio do padrão
                spec.fixed[name] = _check_fixed(name, match.group("value"))
            literal, position = "", match.end()
        spec.separators.append(literal + segment[position:])
        if not spec.fields:
            raise PatternError("O padrão precisa de parâmetros, ex.: @name - @vol.")
    # Um separador do padrão não pode ter sido cortado pelo ';' (ex.: "@name -; @auth=x").
    named = [f for f in spec.fields if f != "skip"]
    if len(named) != len(set(named)):
        raise PatternError("Cada parâmetro (@name, @vol, @auth...) só pode aparecer uma vez.")
    if spec.has_pattern and "title" not in spec.fields and "title" not in spec.fixed \
            and "series" not in spec.fields + list(spec.fixed):
        raise PatternError("Use @name no padrão ou defina um título fixo (@name=...).")
    return spec


def _swallowed_separator(spec: ImportSpec, found: re.Match, count: int) -> bool:
    """Num match encurtado (partes do fim faltando), a última parte capturada não
    pode conter o delimitador da parte seguinte: isso indica que o arquivo tinha
    mais partes, só que fora do padrão."""
    core = spec.separators[count].strip()
    if not core:
        return False
    value = found.group(f"p{count - 1}") or ""
    chars = "".join("[-–—]" if char in "-–—" else re.escape(char) for char in core)
    return re.search(rf"\s{chars}\s", value) is not None


def _match_pattern(stem: str, spec: ImportSpec) -> dict[str, str] | None:
    """Partes do nome segundo o padrão; None se o arquivo não segue o padrão."""
    text = strip_noise(normalize_text(stem))
    values: dict[str, str] = {}
    if "year" not in spec.fields:
        text, year = extract_year(text)
        text = strip_noise(text)
        if year:
            values["year"] = str(year)
    # As partes do fim podem faltar, mas o título tem de vir do nome (ou ser fixo).
    needs = {"title", "series"} if "title" not in spec.fixed else set()
    found = None
    for count in range(len(spec.fields), 0, -1):
        if needs and not needs & set(spec.fields[:count]):
            break
        for strict in (True, False):
            found = spec.regex(count, strict).match(text)
            if found and count < len(spec.fields) and _swallowed_separator(spec, found, count):
                found = None  # "Dom Casmurro - Machado" não é "@name" sem o resto
            if found:
                break
        if found:
            break
    if found is None:
        return None
    for index, field_name in enumerate(spec.fields):
        value = (found.groupdict().get(f"p{index}") or "").strip()
        if value and field_name != "skip":
            values[field_name] = value
    if "volume" in spec.fields and "volume" not in values and values.get("title"):
        # O padrão tem @vol, mas este arquivo não separou: "Naruto v03", "Berserk Vol. 41".
        trailing = VOL_TRAILING.search(values["title"])
        if trailing and trailing.start() > 0:
            values["volume"] = trailing.group(0).strip()
            values["title"] = values["title"][:trailing.start()].strip()
    return values


def apply_spec(stem: str, spec: ImportSpec | None,
               author_first: bool = True) -> tuple[ParsedName, bool]:
    """Lê o nome do arquivo segundo "Como importar".

    Devolve (resultado, seguiu_o_padrão). Sem padrão (ou fora dele) usa o modo
    automático. Os valores fixos (@auth=ONE) valem para todos os arquivos.
    """
    values = _match_pattern(stem, spec) if spec is not None and spec.has_pattern else None
    matched = values is not None
    if values is None:
        values = automatic_values(stem, author_first)
    if spec is not None:
        values.update(spec.fixed)
    return compose(values), matched or spec is None or not spec.has_pattern
