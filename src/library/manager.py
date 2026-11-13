"""Names required by the external e-book manager (the owner of the library).

This is the only place in the code that names the external program: executable
names, environment variables, configuration folders and OPF format markers. These
values are a contract with the external program and cannot be changed.
"""

PRODUCT = "Calibre"  # name shown to the user ("Calibre não encontrado: instale-o...")

# Command line tool
CLI_NAME = "calibredb"
LANGUAGE_ENV = "CALIBRE_OVERRIDE_LANG"  # forces the output in English (see cli.py)
INSTALL_DIRS = (
    r"C:\Program Files\Calibre2",
    r"C:\Program Files (x86)\Calibre2",
    "/Applications/calibre.app/Contents/MacOS",
    "/usr/bin",
    "/opt/calibre",
)

# Configuration of the program (to find the libraries it already knows)
CONFIG_DIR_ENV = "CALIBRE_CONFIG_DIRECTORY"
CONFIG_DIR_NAME = "calibre"
CURRENT_LIBRARY_FILE, CURRENT_LIBRARY_KEY = "global.py.json", "library_path"
RECENT_LIBRARIES_FILE, RECENT_LIBRARIES_KEY = "gui.json", "library_usage_stats"
DEFAULT_LIBRARY_NAME = "Calibre Library"

# Library and OPF format
DATABASE_FILE = "metadata.db"
OPF_TRUSTED_SCHEME = "calibre"  # without this identifier the program ignores the whole OPF
OPF_META_PREFIX = "calibre:"  # calibre:series, calibre:series_index, calibre:title_sort
