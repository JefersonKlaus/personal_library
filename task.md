## What is the project?
The project is a desktop system that convert PDF to calibre app using python. At this case 'convert' means, create a file that Calibe uses to manage the books. 
The first goal is review the exportation process, because it is not working in the new calibre's version and ADD GROQ AI to help on the process.
The second goal, is add the feature to be able to load the calibe documents in my app and to view them like it appears in the calibre app.
The last goal, is refact to improve the code, applying KISS and SRP and of course, improve the tests.

## Task
Preserve the current analysis, metadata review, organization, undo, and optional Calibre import flows. Add an in-app library view that reads the exported Calibre library and displays each book with its cover when available, title, author, language, tags, file location, and export status. Provide a refresh action after exporting or importing, show clear errors for invalid libraries or missing data, and handle empty libraries, duplicates, incomplete metadata, missing covers, and failed exports without reporting false success.

## How to judge completion

Analyze and organize a set of PDFs, then open or refresh the new library view. Every exported book should appear in the calibre and all the calibre's galery needs to open in my app.
So validate it you will need to run main.py script using FLET and test the app, and after that run pytest and see the result.


## Notes
This is a open source project that I started to automaticaly convert the PDF books to calibres format, you can find the code here https://github.com/JefersonKlaus/personal_library. This project is not working in the new calibre's version, so I need to fix it and add more features, like, using AI to create the metadas that Calibe uses, and be able to import the calibre's galery to my app and add more books and exrpot it back to calibre.


## How to test

```powershell
cd D:\codigo\personal_library
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
python main.py
```

Manually test the complete flow: add PDFs, analyze and review metadata, simulate, organize, optionally import into Calibre, and refresh the library view. Also test invalid or empty libraries, missing covers and metadata, failed exports, and undo.

Run the automated tests:

```powershell
python -m pytest
```

Tests should cover library reading and display, metadata and covers, invalid or empty libraries, refresh after export/import/undo, and all existing analysis, organization, undo, and `calibredb` integration behavior.

## Evidence

```text
ACTION: python main.py
RESULT: The app opened, books were exported, and the Calibre-like library view was verified.

ACTION: python -m pytest
RESULT: [number] passed
```


UPDATED:
pdf2calibre\metadata.py
pdf2calibre\models.py
pdf2calibre\naming.py
pdf2calibre\opf.py
pdf2calibre\organizer.py
pdf2calibre\planner.py
pdf2calibre\settings.py
pdf2calibre\ui.py
pdf2calibre\calibre.py
main.py

CREATED:
pdf2calibre\exporter.py
pdf2calibre\gallery_ui.py
pdf2calibre\library_import.py
pdf2calibre\library.py

TESTS:
tests\conftest.py
tests\test_exporter_import.py (CREATED)
tests\test_library.py (CREATED)
tests\test_metadata.py
tests\test_naming.py
tests\test_opf_calibre_settings.py
tests\test_organizer.py
tests\test_planner.py
tests\test_ui_wiring.py