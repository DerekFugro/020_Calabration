"""Capture stays separate (docs/capture): src/capture imports only the allowed shared modules,
and nothing else in src/ imports src.capture (the start screen starts it as a process)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {"src.camera_db", "src.van_scan", "src.version", "src.styles", "src.paths"}
LATER = {"src.detector", "src.dot_detector", "src.board", "src.boards", "src.coverage"}  # live guidance / auto grab


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))    # some files start with a BOM
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_capture_imports_only_allowed_shared_modules():
    bad = []
    for f in (ROOT / "src" / "capture").rglob("*.py"):
        for m in _imports(f):
            if m.startswith("src.") and not m.startswith("src.capture") and m not in ALLOWED | LATER:
                bad.append(f"{f.name}: {m}")
    assert not bad, bad


def test_nothing_outside_capture_imports_it():
    bad = []
    for f in list((ROOT / "src").rglob("*.py")) + [ROOT / "main.py", ROOT / "cli.py"]:
        if "capture" in f.relative_to(ROOT).parts[:2]:
            continue
        bad += [f"{f.relative_to(ROOT)}: {m}" for m in _imports(f) if m.startswith("src.capture")]
    assert not bad, bad
