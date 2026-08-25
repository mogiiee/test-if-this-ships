from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "context"


def load_grass_context() -> str:
    files = sorted(ROOT.glob("*.md"))
    parts = [f"--- {f.name} ---\n{f.read_text(encoding='utf-8').strip()}" for f in files]
    return "\n\n".join(parts)
