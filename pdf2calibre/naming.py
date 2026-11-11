"""Limpeza de nomes: arquivo -> título/autor, e nomes seguros para pastas."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

_INVALID_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Marcas que sites de download deixam no nome do arquivo.
_NOISE_PATTERNS = [
    re.compile(r"\(?\s*\bz-?lib(?:rary)?(?:\.org)?\s*\)?", re.I),
    re.compile(r"\blibgen(?:\.\w+)?\b", re.I),
    re.compile(r"\bwww\.\S+", re.I),
    re.compile(r"[\(\[]\s*pdf\s*[\)\]]", re.I),
    re.compile(r"[\(\[]\s*(?:e-?book|ocr|scan(?:ned)?)\s*[\)\]]", re.I),
    re.compile(r"\s*[-–]\s*(?:copy|c[óo]pia)(?:\s*\(\d+\))?\s*$", re.I),
    re.compile(r"\s*\(\d{1,2}\)\s*$"),
]
_YEAR = re.compile(r"[\(\[]\s*((?:1[5-9]|20)\d{2})\s*[\)\]]")
_SEPARATOR = re.compile(r"\s+[-–—]\s+")

# Palavras minúsculas aceitas dentro de nomes de pessoas.
_PARTICLES = {
    "de", "da", "do", "dos", "das", "del", "della", "di", "du",
    "van", "von", "der", "den", "la", "le", "el", "bin", "ibn", "al",
}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "filho", "neto", "junior", "júnior", "sobrinho"}
_CORPORATE = re.compile(
    r"\b(ltd|ltda|inc|llc|corp|gmbh|editora|press|university|universidade|"
    r"instituto|institute|association|associação|company)\b",
    re.I,
)
_ARTICLES = {"the", "a", "an", "o", "os", "as", "um", "uma", "el", "la", "los", "las", "le", "les"}


@dataclass
class ParsedName:
    """Resultado de interpretar um nome de arquivo."""

    title: str
    author: str = ""
    year: int | None = None
    series: str = ""
    series_index: float | None = None  # número do volume
    publisher: str = ""
    language: str = ""
    tags: list[str] = field(default_factory=list)
    series_from_name: bool = False  # série veio do @name (há volume, mas não @series)


# ---------------------------------------------------------------- volumes

_VOL_WORD = r"(?:vol(?:ume)?|tomo|livro|book|parte|part|n[º°]|#)"
_VOL_NUMBER = r"\d{1,4}(?:[.,]\d+)?"
# Uma parte inteira que é só o volume: "Vol 18", "Volume 41", "v03", "Tomo 2", "03".
_VOL_PART = re.compile(
    rf"^(?:(?P<word>{_VOL_WORD})\.?\s*|(?P<v>v)\.?\s*(?=\d))?(?P<num>{_VOL_NUMBER})$", re.I)
# Volume no fim do texto, sem separador: "Naruto v03", "Berserk Vol. 41".
_VOL_TRAILING = re.compile(
    rf"\s+(?:(?P<word>vol(?:ume)?|tomo)\.?\s*|(?P<v>v)(?=\d))(?P<num>{_VOL_NUMBER})$", re.I)


def _volume_from(match: re.Match) -> tuple[str, float]:
    """('Vol 18', 18.0) a partir de um match de volume; 'v03' e '03' viram 'Vol. 03'."""
    number = match.group("num")
    value = float(number.replace(",", "."))
    if match.group("word"):
        return match.group(0).strip(), value
    return f"Vol. {number}", value


def match_volume(text: str, bare_digits: int = 3) -> tuple[str, float] | None:
    """Se o texto inteiro é um volume, devolve (rótulo, número).

    Números sem prefixo só valem até `bare_digits` dígitos: "03" é volume,
    "2049" (em "Blade Runner - 2049") não.
    """
    match = _VOL_PART.match(text.strip())
    if not match:
        return None
    if not (match.group("word") or match.group("v")) and \
            len(match.group("num").split(".")[0].split(",")[0]) > bare_digits:
        return None
    return _volume_from(match)


def looks_like_volume(text: str) -> bool:
    """'Vol 01', 'Volume 41', 'v03' (com prefixo): serve para avisar quando o padrão pôs
    um volume no lugar do autor ou do título."""
    match = _VOL_PART.match((text or "").strip())
    return bool(match and (match.group("word") or match.group("v")))


def normalize_text(text: str) -> str:
    """Unicode NFC, '_' vira espaço e espaços repetidos são colapsados."""
    text = unicodedata.normalize("NFC", text).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def strip_noise(text: str) -> str:
    """Remove marcas de sites de download e sufixos de cópia."""
    for _ in range(2):  # a remoção de um padrão pode expor outro
        for pattern in _NOISE_PATTERNS:
            text = pattern.sub(" ", text)
    return normalize_text(text).strip(" -–._")


def extract_year(text: str) -> tuple[str, int | None]:
    """Extrai '(2019)' ou '[2019]' do texto; devolve (texto sem o ano, ano)."""
    match = None
    for match in _YEAR.finditer(text):
        pass  # fica com a última ocorrência
    if match is None:
        return text, None
    cleaned = normalize_text(text[: match.start()] + " " + text[match.end():])
    return cleaned, int(match.group(1))


def looks_like_person(text: str) -> bool:
    """Heurística: 1 a 5 palavras capitalizadas, sem números."""
    words = text.replace(".", ". ").split()
    if not 1 <= len(words) <= 5 or len(text) > 60:
        return False
    if any(char.isdigit() for char in text):
        return False
    for word in words:
        base = word.strip(".,")
        if not base or base.lower() in _PARTICLES:
            continue
        if not base[0].isupper():
            return False
    return True


_PEOPLE_SEPARATOR = re.compile(r"\s*;\s*|\s+&\s+|\s+and\s+|\s+e\s+", re.I)


def author_score(text: str) -> int:
    """Quanto o texto parece ser autor(es): 2 = várias pessoas, 1 = uma, 0 = não.

    "Ana Lima e Rui Dias" vale 2. Cada nome precisa ter 2+ palavras, senão
    títulos como "Guerra e Paz" ou "Romeu & Julieta" passariam por autores.
    """
    parts = [part for part in _PEOPLE_SEPARATOR.split(text) if part.strip()]
    if len(parts) >= 2 and all(len(part.split()) >= 2 and looks_like_person(part)
                               for part in parts):
        return 2
    return 1 if looks_like_person(text) else 0


def _title_and_author(text: str, author_first: bool) -> tuple[str, str]:
    """Separa título e autor de um texto já limpo (sem ano nem volume)."""
    parts = _SEPARATOR.split(text)
    if len(parts) >= 2:
        head, tail = parts[0], " - ".join(parts[1:])
        last, rest = parts[-1], " - ".join(parts[:-1])
        # (autor, título) para cada orientação possível
        preferred = (head, tail) if author_first else (last, rest)
        other = (last, rest) if author_first else (head, tail)
        # A orientação escolhida pelo usuário vence, a não ser que o outro lado
        # pareça mais com autor(es) (ex.: "Física Básica - Ana Lima & Rui Dias").
        if author_score(preferred[0]) >= author_score(other[0]):
            author, title = preferred
        else:
            author, title = other
        return title, author

    match = re.match(r"^(?P<title>.+?)\s*[\(\[](?P<author>[^\)\]]+)[\)\]]$", text)
    if match and looks_like_person(match.group("author")):
        return match.group("title"), match.group("author")

    match = re.match(r"^(?P<title>.+?)\s+(?:by|por)\s+(?P<author>.+)$", text, re.I)
    if match and looks_like_person(match.group("author")):
        return match.group("title"), match.group("author")
    return text, ""


def _split_volume(text: str) -> tuple[str, str, tuple[str, float]] | None:
    """Acha o volume e a obra a que ele pertence: (obra, resto, (rótulo, número)).

    O volume fica colado na obra: em "One Punch Man - Vol 18 - ONE" e em
    "ONE - One Punch Man - Vol 18" a obra é a parte logo antes do volume, e o
    que sobra ("ONE") é o autor.
    """
    parts = _SEPARATOR.split(text)
    if len(parts) >= 2:
        for index in range(len(parts) - 1, -1, -1):  # o volume costuma vir no fim
            volume = match_volume(parts[index])
            if volume:
                name_index = index - 1 if index > 0 else index + 1
                others = [part for i, part in enumerate(parts) if i not in (index, name_index)]
                return parts[name_index], " & ".join(others), volume
    for index, part in enumerate(parts):  # "Naruto v03", "Berserk Vol. 41 - Kentaro Miura"
        match = _VOL_TRAILING.search(part)
        if match and match.start() > 0:
            others = [other for i, other in enumerate(parts) if i != index]
            return part[:match.start()].strip(), " & ".join(others), _volume_from(match)
    return None


def _automatic_values(stem: str, author_first: bool) -> dict[str, str]:
    """Partes deduzidas do nome do arquivo, ainda em texto: title, author, year, volume."""
    original = normalize_text(stem)
    text = strip_noise(original)
    text, year = extract_year(text)
    text = strip_noise(text)
    values = {"year": str(year)} if year else {}
    if not text:
        values["title"] = original or "Sem título"
        return values
    found = _split_volume(text)
    if found is None or not found[0]:
        values["title"], values["author"] = _title_and_author(text, author_first)
    else:
        values["title"], values["author"], (values["volume"], _number) = found
    return values


def compose(values: dict[str, str]) -> ParsedName:
    """Monta o resultado a partir das partes em texto: cada parte vai para o seu campo.

    O título é exatamente o @name. O volume vira o número na série; sem @series, a
    série é o próprio @name, porque o Calibre só guarda o número dentro de uma série
    (sem série ele descarta o volume).
    """
    name = values.get("title", "").strip()
    series = values.get("series", "").strip()
    year_digits = re.sub(r"\D", "", values.get("year", ""))
    parsed = ParsedName(
        title=name or series or "Sem título", author=values.get("author", "").strip(),
        year=int(year_digits) if len(year_digits) == 4 else None, series=series,
        publisher=values.get("publisher", "").strip(),
        language=values.get("language", "").strip(),
        tags=[tag.strip() for tag in values.get("tags", "").split(",") if tag.strip()])
    volume = match_volume(values["volume"], bare_digits=4) if values.get("volume") else None
    if volume is not None:
        parsed.series_index = volume[1]
        if not series:
            parsed.series, parsed.series_from_name = parsed.title, True
    return parsed


def parse_filename(stem: str, author_first: bool = True) -> ParsedName:
    """Descobre título, autor, ano e volume a partir do nome do arquivo (sem extensão).

    Reconhece "Autor - Título", "Título - Autor", "Título (Autor)", "Título by/por
    Autor" e volumes ("Vol 18", "Volume 41", "v03", "- 03"). Quando nada indica o
    autor, devolve só o título.
    """
    return compose(_automatic_values(stem, author_first))


# ---------------------------------------------------------------- como importar (padrão do usuário)

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
    "volume": rf"(?:{_VOL_WORD}\.?\s*|v\.?\s*(?=\d))?{_VOL_NUMBER}",
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
        trailing = _VOL_TRAILING.search(values["title"])
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
        values = _automatic_values(stem, author_first)
    if spec is not None:
        values.update(spec.fixed)
    return compose(values), matched or spec is None or not spec.has_pattern


def display_name(name: str) -> str:
    """'Silva, João' -> 'João Silva'. Outros nomes ficam como estão."""
    name = normalize_text(name)
    if name.count(",") == 1:
        last, first = (part.strip() for part in name.split(","))
        small = len(first.split()) <= 3 and len(last.split()) <= 3
        if first and last and small and first.strip(".").lower() not in _SUFFIXES:
            return f"{first} {last}"
    return name


def split_authors(raw: str) -> list[str]:
    """Separa vários autores ('A; B', 'A & B', 'A and B', 'Ana Lima e Rui Dias')."""
    raw = normalize_text(raw)
    if not raw:
        return []
    pieces: list[str] = []
    for chunk in re.split(r"\s*;\s*|\s+&\s+|\s+and\s+", raw, flags=re.I):
        sub = re.split(r"\s+e\s+", chunk)
        multi = len(sub) > 1 and all(
            len(item.split()) >= 2 and looks_like_person(item) for item in sub
        )
        pieces.extend(sub if multi else [chunk])
    return [display_name(piece.strip(" ,")) for piece in pieces if piece.strip(" ,")]


def author_sort(name: str) -> str:
    """Forma de ordenação do Calibre: 'João da Silva' -> 'Silva, João da'."""
    name = normalize_text(name)
    if not name or "," in name or _CORPORATE.search(name):
        return name
    tokens = name.split()
    suffix: list[str] = []
    while len(tokens) > 1 and tokens[-1].strip(".").lower() in _SUFFIXES:
        suffix.insert(0, tokens.pop())
    if len(tokens) == 1:
        return name
    last = tokens.pop()
    result = f"{last}, {' '.join(tokens)}"
    return f"{result} {' '.join(suffix)}" if suffix else result


def title_sort(title: str) -> str:
    """'The Hobbit' -> 'Hobbit, The' (artigos iniciais vão para o fim)."""
    words = title.split()
    if len(words) >= 2 and words[0].lower() in _ARTICLES:
        return f"{' '.join(words[1:])}, {words[0]}"
    return title


def sanitize_component(text: str, max_len: int = 80, fallback: str = "_") -> str:
    """Deixa o texto válido como nome de pasta/arquivo no Windows, Linux e macOS."""
    text = re.sub(r"\s*:\s*", " - ", normalize_text(text))  # "Título: Sub" -> "Título - Sub"
    text = _INVALID_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.split(".")[0].upper() in _RESERVED_NAMES:
        text = f"_{text}"
    if len(text) > max_len:
        cut = text[:max_len]
        space = cut.rfind(" ")
        if space >= max_len // 2:
            cut = cut[:space]
        text = cut.strip(" .-_")
    return text or fallback


def book_stem(title: str, author: str, max_len: int = 80) -> str:
    """Nome do arquivo no estilo do Calibre: 'Título - Autor'."""
    title_part = sanitize_component(title, max_len, "Sem título")
    author_part = sanitize_component(author, max(20, max_len // 2), "Unknown")
    return f"{title_part} - {author_part}"


def natural_key(path: Path) -> list[object]:
    """Chave de ordenação natural: 'livro2' vem antes de 'livro10'."""
    return [int(piece) if piece.isdigit() else piece.casefold()
            for piece in re.split(r"(\d+)", str(path))]
