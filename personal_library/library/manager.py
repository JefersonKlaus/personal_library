"""Nomes exigidos pelo gerenciador de e-books externo (o dono da biblioteca).

É o único lugar do código que cita o programa externo: nomes de executável,
variáveis de ambiente, pastas de configuração e marcas do formato OPF. Esses
valores são contrato do programa externo e não podem ser trocados.
"""

PRODUCT = "Calibre"  # nome mostrado ao usuário ("feche o Calibre antes de importar")

# Ferramenta de linha de comando
CLI_NAME = "calibredb"
LANGUAGE_ENV = "CALIBRE_OVERRIDE_LANG"  # força a saída em inglês (ver cli.py)
INSTALL_DIRS = (
    r"C:\Program Files\Calibre2",
    r"C:\Program Files (x86)\Calibre2",
    "/Applications/calibre.app/Contents/MacOS",
    "/usr/bin",
    "/opt/calibre",
)

# Configuração do programa (para achar as bibliotecas que ele já conhece)
CONFIG_DIR_ENV = "CALIBRE_CONFIG_DIRECTORY"
CONFIG_DIR_NAME = "calibre"
CURRENT_LIBRARY_FILE, CURRENT_LIBRARY_KEY = "global.py.json", "library_path"
RECENT_LIBRARIES_FILE, RECENT_LIBRARIES_KEY = "gui.json", "library_usage_stats"
DEFAULT_LIBRARY_NAME = "Calibre Library"

# Biblioteca e formato OPF
DATABASE_FILE = "metadata.db"
OPF_TRUSTED_SCHEME = "calibre"  # sem este identificador o programa ignora o OPF inteiro
OPF_META_PREFIX = "calibre:"  # calibre:series, calibre:series_index, calibre:title_sort
