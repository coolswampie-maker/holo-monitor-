import sys

# Настройка окружения выполняется до импорта numpy и sklearn.
from ._compat import setup as _setup
_setup()

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
