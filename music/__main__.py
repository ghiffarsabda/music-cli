"""Entrypoint module for python -m music execution."""

import sys
from music.cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
