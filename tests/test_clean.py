"""The public repository must never mention the real company it was inspired by,
and the prose follows the house style (no em dashes)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = ["hbm", "lafarge", "holcim", "supaset", "powermax", "supafix", "ewekoro", "sagamu",
          "mfamosing", "ashaka", "elephant cement", "dangote", "bua cement", "julius berger",
          "unicem", "watershield"]
TEXT = {".py", ".md", ".css", ".js", ".txt", ".toml", ".example", ".yml", ".yaml", ".svg", ".cfg"}


def _files():
    for p in ROOT.rglob("*"):
        if p.is_file() and (p.suffix in TEXT or p.name in (".env.example", ".gitignore")) \
                and ".git" not in p.parts and "__pycache__" not in p.parts:
            yield p


def test_no_reference_to_real_companies():
    hits = []
    for p in _files():
        text = p.read_text(encoding="utf-8", errors="ignore").lower()
        for word in BANNED:
            if word in text and p.name != "test_clean.py":
                hits.append(f"{p.relative_to(ROOT)}: {word}")
    assert not hits, hits


def test_no_em_dashes():
    dash = chr(0x2014)
    hits = [str(p.relative_to(ROOT)) for p in _files()
            if p.name != "test_clean.py" and dash in p.read_text(encoding="utf-8", errors="ignore")]
    assert not hits, hits
