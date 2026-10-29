"""conftest.py — Ensure the project root is on sys.path for all tests."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
