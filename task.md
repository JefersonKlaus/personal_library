0:20



## Task
The project is a desktop system that convert PDF to calibre app using python. At this case 'convert' means, create a file that Calibe uses to manage the books. 
The first goal is create the options to update metadata of one book or many books.
The second goal, is add the feature of convert PDF to EPUB
The last goal, improve the usability, 

## How to judge completion

Run the app (desktop) create a library,  and import more books fot it, after need choose a differente library and import book for it. With the library OK, you need to edit the metadata of ONE book, and after many books together. And finally be able to convert the PDF to EPUB format.
After all the manual test, run the pytest.


## Notes
This is a open source project that I started to automaticaly convert the PDF books to calibres format, you can find the code here https://github.com/JefersonKlaus/personal_library. Now this project is working as a personal library where I can import my books there and read theam.  But, after import my books I can not updatem them, so this task is to make it possible, and be possible convert the books to EPUB format.
Now the app has 234 tests, so, probably I will add more.


## How to test

O ran the and i test it manually, adding PDFs, analyzing and reviwing the metadata, I created a new library and imported many PDFs. After I got a existent library and imported new books in there. Alfter that I ran pytest.

SETUP:
cd workspace/personal_library
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt


ACTION: flet run
RESULT: The app opened and I used it

ACTION: pytest
RESULT: 234 passed, 5 skipped in 12.7


O ran the and i test it manually, adding PDFs, analyzing and reviwing the metadata, I created a new library and imported many PDFs. After I got a existent library and imported new books in there. Alfter that I ran pytest.

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