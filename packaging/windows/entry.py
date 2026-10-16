"""PyInstaller entry script for the Windows desktop app; see ``pitwall/desktop.py``."""

import sys

from pitwall.desktop import main

if __name__ == "__main__":
    sys.exit(main())
