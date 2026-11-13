# Personal Library

Desktop app (Python + Flet) to look after your PDF library in Calibre:

1. **Import**: choose PDFs; title and author are read and adjusted automatically (metadata
   from inside the PDF, the file name, junk such as "Microsoft Word - doc1" or "admin" is
   discarded, identical files are detected). You check the data and import it into your
   Calibre library.
2. **Gallery**: the Calibre library as a grid of covers, with search and details.
3. **Export**: copies books of the library to another folder, in the Calibre layout.

> The app window is in Portuguese. This README names the buttons exactly as they appear on
> screen (**Importar**, **Analisar**, **Exportar**...), with the explanation in English.

## Install and open

In the project folder:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
flet run
```

`flet run` opens the app in the desktop window (it runs the `main.py` of this folder). Other
ways:

| Command            | What it does                                                        |
|--------------------|---------------------------------------------------------------------|
| `flet run`         | opens the app                                                       |
| `flet run -r`      | opens it and restarts on its own when any code file changes          |
| `flet run --web`   | opens it in the browser                                             |
| `python main.py`   | also opens the app, without the `flet` command                      |

`requirements.txt` installs Flet with `cli` (the `flet` command) and `desktop` (the window);
without them Flet would try to install them on the first run. The project configuration
(name, version, dependencies and `[tool.flet]`) is in `pyproject.toml`, and `flet run`
creates a local `.flet/` working folder, which git already ignores.

You need [Calibre](https://calibre-ebook.com) installed (the app uses its `calibredb` to
import). Settings, log and gallery thumbnails live in `~/.personal_library`.

## How to use

### 1. Importar (import)

1. **Adicionar PDFs…**, **Adicionar pasta…** or paste a path. The analysis starts on its own.
2. If the files follow a format, describe it in **Como importar** (or pick one in
   **Modelos**) and click **Aplicar**: parameters (`@name`, `@vol`, `@auth`...), the
   delimiters between them and fixed values for every PDF (`@auth=ONE`). The example line
   shows how the first file will be read. Empty = automatic.
3. Check title, author, series and volume in the list (edit whatever you need; untick what
   you do not want). Several authors: separate them with `&`.
4. Optional: tags for every book (e.g. `importado`).
5. **Importar para a biblioteca**: the books go to the library chosen in the Galeria tab,
   with title, authors, year, language, tags and cover (1st page). Books the library already
   has (same title and author) are reported and not duplicated.
6. **Desfazer última importação** removes those books (they go to the Calibre recycle bin).

> **If another program is using the library** (for instance Calibre itself, or an e-book
> reader), **close it before importing**: while it is open, the library tool refuses access
> and the app reports "A biblioteca está sendo usada por outro programa".

#### Using Groq AI to fill in the data (optional)

For file names with no pattern (`scan_0042.pdf`, `livro final v2.pdf`), tick **Usar Groq AI
para preencher os dados** and provide the **Groq API key** (create a free one at
<https://console.groq.com/keys>). On **Analisar**, the app first works out the data as usual
and then asks the AI, **one book at a time**, for title, authors, series, volume, year,
publisher and language. The result shows up in the same review list: edit whatever you need
and click **Importar para a biblioteca**, just like in a normal import.

- **What is sent**: file name, title/author from inside the PDF, page count, what the app
  already worked out and the text of the first 3 pages (up to 2,500 characters). The PDF file
  itself is not sent. Image-only PDFs (scanned) have no text: the AI uses the rest alone.
- **Rules**: fixed values of "Como importar" (`@auth=ONE`) always beat the AI; whatever the
  AI does not know keeps what the app worked out. Each book shows "preenchido pela IA (N% de
  confiança)"; below 50% it is left in **atenção** for you to check. If the AI does not
  answer for a book, it keeps the app data and stays in **atenção**.
- **Key**: it is saved in the settings (`~/.personal_library/settings.json`, in plain text).
  If you would rather not save it, leave the field empty and set the `GROQ_API_KEY`
  environment variable.
- **Model**: `llama-3.3-70b-versatile` by default. If Groq retires that model, the app says
  so; change the **Modelo** field to one from the list at
  <https://console.groq.com/docs/models>.
- **Free plan limits**: when Groq asks to wait (error 429), the app waits the given time and
  tries again (up to 4 times). A refused key or no connection stops the queries; the books
  already analysed stay in the list. **Cancelar** stops it at any moment.

#### Which library receives the books

If no library has been chosen yet (or the chosen one was deleted/moved), step 3 shows a
warning with the options:

- **Usar esta**: libraries your Calibre already knows are listed (the app reads the Calibre
  configuration: current library and recently used ones, plus the default `Calibre Library`
  folder in your user folder);
- **Escolher biblioteca existente…**: the folder holding `metadata.db` (picking the folder
  above, such as `Documents`, also works if there is a single library inside it);
- **Criar biblioteca nova…**: choose where; if the folder is not empty, the library is
  created in a `Calibre Library` subfolder. Calibre itself (`calibredb`) creates it, so
  Calibre has to be installed, and no program may be using a library at that moment. To open
  it later in Calibre: **Library > Switch/create library** and choose the folder.

With a library chosen, **Trocar biblioteca…** shows the same options. The library is the same
in the three tabs (Importar, Galeria and Exportar); the Galeria tab also has **Criar nova…**.

#### "Como importar": parameters, delimiters and fixed values

Write the parameters in the order they appear in the file name, with the delimiters used
between them (`-`, `_`, space, parentheses...):

| Parameter    | Means                                         | Also accepted                |
|--------------|-----------------------------------------------|------------------------------|
| `@name`      | title of the work                             | `@nome`, `@title`, `@titulo` |
| `@vol`       | volume: `Vol 18`, `Volume 41`, `v03`, `03`    | `@volume`                    |
| `@auth`      | author(s)                                     | `@autor`, `@author`          |
| `@year`      | year: `1999` or `(1999)`                      | `@ano`                       |
| `@series`    | series, when different from `@name`           | `@serie`                     |
| `@publisher` | publisher                                     | `@editora`                   |
| `@lang`      | language (`pt`, `por`, `en`...)               | `@idioma`                    |
| `@tags`      | tags, separated by commas                     | `@etiquetas`                 |
| `@skip`      | part to ignore                                | `@ignorar`                   |

**Fixed value** (holds for every PDF and beats the file name and the PDF metadata):
`@parameter=value`, at the end of the pattern or separated by `;`.

| Como importar                                        | `One Punch Man - Vol 18` becomes                                |
|------------------------------------------------------|-----------------------------------------------------------------|
| `@name - @vol - @auth`                               | title `One Punch Man`, vol. 18, series `One Punch Man`           |
| `@name - @vol; @auth=ONE`                            | the same, author **ONE** for all                                 |
| `@name - @vol - @auth=ONE`                           | the same; if the file has a 3rd part, it is replaced by ONE      |
| `@name - @vol; @series=Coleção OPM`                  | title `One Punch Man`, vol. 18, series `Coleção OPM`             |
| `@name - @vol; @auth=ONE; @tags=mangá; @publisher=Panini; @lang=pt` | the same, with tag, publisher and language        |
| `@auth=ONE` (no pattern)                             | automatic mode, only the author fixed                            |
| `@vol; @name=One Punch Man` (files `01.pdf`, `02.pdf`...) | fixed title and volume from the file name                   |

Other examples: `@auth - @name (@year)` reads `Machado de Assis - Dom Casmurro (1899)`;
`@series - @vol - @name` reads `Harry Potter - 1 - A Pedra Filosofal`;
`@skip - @name - @auth` ignores the `[Grupo]` of `[Grupo] - Iracema - José de Alencar`.
Parts missing at the end of the name are left empty. Files outside the pattern are left in
**atenção** and are read in automatic mode (the fixed values still hold). When there is a
pattern, the file name counts for more than the metadata inside the PDF, which only fills in
what is missing. The old format (`NOME - VOL - AUTOR`) is still accepted.

**Each parameter fills in its own field only**: `@name` is the title (exactly), `@vol` is the
volume, `@auth` the author, `@series` the series. If the pattern puts something like `Vol 01`
in the author or in the title (e.g. `@name - @auth` on `One Punch Man - Vol 01`), the book is
left in **atenção** and the example line warns "parece um volume: use @vol".

**Volumes and series**: Calibre only keeps the volume number inside a series (with no series
it drops the number). That is why, when there is `@vol` and no `@series`, the series is the
`@name` itself, and the example line shows it ("Série: One Punch Man (de @name)"). For
another series, use `@series` in the pattern or `@series=...`.

**Duplicates**: Calibre treats books with the same title and author as duplicates, and would
refuse volume 2 of "One Punch Man". For volumes, the app compares title + author + series +
volume against the library before importing (the same volume again shows up as "já existe")
and sends the rest for Calibre to accept. In the Galeria tab each cover shows the volume, and
sorting by **Título** or **Série e volume** puts the volumes in order. On export, volumes
with the same title and author get the volume in the file name
(`One Punch Man - Vol. 18 - ONE.pdf`).

Automatic mode (empty field) also recognises volumes (`Vol 18`, `Volume 41`, `v03`, `- 03`)
and follows the same rules.

### 2. Galeria (gallery)

Choose the folder of the Calibre library (the one holding `metadata.db`). The books show up
as a grid of covers like in Calibre: search by title, author, tag, series or publisher
(ignoring accents) and order (most recent, title, series and volume, author, publication).

- **Series sidebar**: "Todos os livros", "Sem série" and each series with its book count.
  Click a series (e.g. *Spider-Geddon*) to see only it, with the volumes in order; the search
  and the order still hold inside the series.
- **Renaming a series**: the small pencil next to the series. It changes the series in every
  book of it and, if you want, the titles equal to the old name too (volumes imported with
  `@name`). If the new name already belongs to another series, the books move into it (the
  dialog says so).
- **Selecting and opening** (like in a file manager):
  - **one click** selects only that book (it gets highlighted);
  - **Ctrl+click** (**Cmd+click** on macOS) adds the book to the selection and keeps the
    others; Ctrl+click on a selected book takes it out;
  - **Shift+click** selects every book from the last clicked one to this one, in the order
    shown (the search, series and sort apply, and the range can span pages);
    **Ctrl+Shift+click** adds that range to the books already selected;
  - the count at the bottom says how many are selected, including those on other pages;
  - **two clicks**, or **right button > Abrir**, open the details window. There, the small
    pencil next to the title renames the book (✓ saves, ✕ cancels) and **Abrir livro**
    opens the book for reading.
- **Reading** (**Abrir livro**): a PDF opens in a **reader window of its own**, one page
  at a time. It is a normal window: maximize, minimize, resize or close it, and keep using
  the app meanwhile; several books can be open at once, each in its window. Turn pages
  with the buttons below the page, by typing the page number, or with the keyboard:
  → ↓ Page Down and space go forward, ← ↑ Page Up go back, Home/End go to the first/last
  page, Esc closes the window. The button at the top right opens the file in the default
  program of the system. Other formats (EPUB...) and PDFs the app cannot read (protected
  by a password, damaged) open in the default program instead.
  - In the web version (`flet run --web`) the book opens inside the app window instead,
    in place of the tabs (**←** or Esc goes back to the gallery).
  - Each reader window is a small separate process (Flet has one window per app). If one
    fails to open, the status bar says so and the error is in
    `~/.personal_library/reader-errors.log`.
- **Editing metadata** (**right button > Editar metadados**):
  - **one book**: every field, filled in, next to the cover: title, authors (separate them
    with `&`), series and volume, publisher, year, tags, languages (`pt`, `en`...),
    identifiers (`isbn:978...`) and description. Only the fields you change are written;
    the sort names of the title and authors follow them automatically;
  - **several books** (right button on one of the selected books): each field has a
    checkbox, and only the ticked fields are written, with the same value in every
    selected book (typing in a field ticks it). "(vários valores)" marks the fields where
    the books differ. Tags and languages replace the ones each book had. Volume and
    identifiers are edited one book at a time;
  - only the books on screen are edited (a selected book hidden by the search or the
    series filter is left alone). Invalid values (a year like `ontem`, a language like
    `português`) are pointed out in the dialog, and nothing is written until they are fixed.

To display them, the gallery only reads the library (database opened read-only) and works
with Calibre open. Renaming goes through the library tool (`calibredb`), like importing: if
another program is using the library, close it first. The gallery refreshes on its own after
importing or renaming.

### 3. Exportar (export)

Tick the books of the library (they all start ticked; the filter and "Marcar/Desmarcar todos"
help you choose), choose the destination folder and click **Exportar**. Each book becomes:

```
Autor/Título/Título - Autor.pdf     (and the other formats the book has)
Autor/Título/Título - Autor.opf     all the metadata: series, publisher, ISBN, description...
Autor/Título/cover.jpg
```

**Simular** shows what would be done without touching the disk; **Desfazer última** deletes
the export. The exported folder goes into any Calibre with *Add books → Add from folders and
sub-folders*, by dragging the PDFs or through the auto-add folder (in that case untick "One
folder per book", because Calibre does not look into subfolders).

> The destination cannot be a Calibre library: Calibre only shows books registered in
> `metadata.db`, and files copied straight there would stay invisible. To put books into a
> library, use the Importar tab.

The bottom bar shows the progress, the **Cancelar** button and the latest message;
**Registro** opens the history (it opens on its own when there is an error).

## How the library reads the metadata

Rules checked in the Calibre code (`calibre/ebooks/metadata/meta.py` and `opf2.py`); the
names it requires are all in `src/library/manager.py`:

- Only an `.opf` carrying the `opf:scheme="calibre"` identifier is used. Without it the file
  is ignored and the data from inside the PDF wins ("Microsoft Word - doc1", "admin"...).
- For a PDF added on its own, only the `.opf` **with the same name** as the PDF is read.
  That is why the app writes `Título - Autor.opf`.
- The year goes as `YYYY-01-01T12:00:00+00:00`: with midnight UTC it would show up as
  December of the previous year in time zones such as Brazil's.
- The `opf:file-as` of every author carries the sort name of the whole book
  (`Lima, Ana & Dias, Rui`), which is how the library writes and reads it.
- The command line tool (`calibredb`) is called with the output in English, so the app
  understands the answer even when the program is in Portuguese.
- Importing goes through a temporary folder (PDF + `.opf` + cover) and the tool; the
  temporary folder is deleted at the end, even on error.

## Safety of the files

- The source PDFs are never changed nor deleted.
- Copies are written as `.part`, verified (size and SHA-256) and only then renamed; the
  `.opf` and the cover are written first, so the book never shows up without them.
- The library is only changed by Calibre's own tool (`calibredb`); the app merely reads its
  database (in read-only mode).
- Undo never overwrites files; undone imports go to the Calibre recycle bin.
- If the disk has no room for the batch, nothing is copied.
- No PDF leaves your computer and there is no telemetry. The app only uses the network if you
  tick **Usar Groq AI**: in that case, the text clues of each book (see above) go to Groq.

## Structure

The code lives in `src/`, split into folders by subject. Each folder only uses the ones below
it:

```
ui/                        the interface
importing/  exporting/     the logic of the Importar and Exportar tabs
library/                   the e-book library
parsing/  pdf/             file name and PDF content
core/                      the base
```

The logic does not know about the interface, and only `library/` knows about the external
program. The one exception to the order: `core/settings.py` takes the name of the default
Groq model from `importing/groq_client.py`.

```
pyproject.toml             project, dependencies and `flet run` configuration
main.py                    entry point (what `flet run` executes)
src/
  __init__.py              name and version of the app

  core/                    base used by the whole app
    paths.py               app folders (~/.personal_library)
    settings.py            settings (settings.json)
    logging_setup.py       file log
    models.py              BookEntry, ImportOptions, Status
    files.py               verified copy, disk space, undo (manifest), open with the system
    text.py                text cleanup, safe file names, accent-insensitive search

  parsing/                 book data from the file name
    people.py              person names: recognise, split, sort
    volumes.py             volumes in the name ("Vol 18", "v03")
    filename_parser.py     automatic mode: title/author/volume from the file name
    import_spec.py         "Como importar": @name - @vol; @auth=ONE (and its example line)

  pdf/                     reading PDFs
    pdf_reader.py          metadata from inside the PDF (and what is junk)
    pdf_cover.py           cover = 1st page
    pdf_pages.py           pages as images, one at a time (for the reader)

  importing/               Importar tab (the logic)
    analysis.py            find PDFs, build each book, duplicates
    groq_client.py         client of the Groq API (waits, retries, errors)
    ai_metadata.py         "Usar Groq AI": clues of each PDF -> book data
    importer.py            reviewed PDFs -> library (and undo)

  exporting/               Exportar tab (the logic)
    exporter.py            library -> folder with .opf and cover

  library/                 the e-book library
    manager.py             THE ONLY place with the names of the external program
    database.py            read-only access to the library database
    search.py              search and order
    thumbnails.py          cover thumbnails
    opf.py                 .opf format
    location.py            validate, find and where to create libraries
    cli.py                 command line tool: add, remove, create
    renamer.py             rename books and series (through the library tool)
    metadata_editor.py     edit the metadata of one book or many (through the library tool)

  ui/                      Flet interface
    app.py                 window, status bar, jobs and the open library
    widgets.py             reused pieces (sections, paging, colours)
    library_picker.py      choose/create/switch the library
    import_tab.py          Importar tab
    export_tab.py          Exportar tab
    gallery_tab.py         Galeria tab: grid, filters, pages; wires each card to the modules below
    selection.py           selection rules: click, Ctrl+click, Shift+click (no Flet)
    keyboard.py            are Shift/Ctrl held? (the window keyboard listener)
    book_views.py          cover, card and details window of a book
    series_sidebar.py      series sidebar (filter and rename)
    metadata_dialog.py     the "Editar metadados" dialog (one book or several)
    library_edits.py       runs a change through the library tool and reports it
    book_opener.py         Abrir livro: reader window, reader in the app, or default program
    reader.py              reading a PDF, one page at a time (the reader itself)
    reader_launcher.py     starts a reader window (a separate process)
    reader_window.py       the reader window program (what runs in that process)
tests/                     pytest, in folders that mirror src/ (tests/ui/test_gallery_tab.py
                           tests src/ui/gallery_tab.py); helpers.py: shared test helpers,
                           conftest.py: fixtures
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests are in folders that mirror `src/`: the tests of `src/library/search.py` are in
`tests/library/test_search.py`. `tests/helpers.py` has what several tests share (test PDFs, a
sample library, a fake Flet, a fake library tool, the gestures of the gallery) and
`tests/conftest.py` the fixtures. Run one folder with `python -m pytest tests/ui`.

Most interface tests use a fake Flet: they check the wiring logic, **not** the looks.
`tests/ui/test_real_flet.py` builds the screens and dialogs with the installed Flet, which
catches control arguments that do not exist in it; it still draws nothing, so open the app
and test it by hand too.

## Known limits

- Reading the author from the file name is a heuristic: check the list before importing.
- The AI gets things wrong too (and may "make things up"): check the list, above all the
  books left in atenção.
- Author lists separated by commas alone (`Silva, Souza, Lima`) are not split; use `&`.
- The library tool refuses access while another program is using it (close it to import).
- Reader windows need Python, so they work when the app runs with `flet run` or
  `python main.py`; a packaged app reads the book inside its own window instead.
- The gallery shows 60 books per page and only renames books and series (the rest of the
  editing is left to Calibre).
