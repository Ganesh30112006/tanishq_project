#!/usr/bin/env python
"""Django management entrypoint for the CareSense AI application backend."""
from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ImportError(
            "Couldn't import Django. Are you in the right virtual environment and "
            "have you installed the base dependencies (pip install -e .)?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
