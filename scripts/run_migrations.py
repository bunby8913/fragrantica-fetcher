#!/usr/bin/env python3
"""Run database migrations without starting the Flask server."""

from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import run_migrations  # noqa: E402


def main() -> None:
    load_dotenv(ROOT / ".env")
    run_migrations()
    print("Database migrations completed.")


if __name__ == "__main__":
    main()
