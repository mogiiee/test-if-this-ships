from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "context"


def load_grass_context(*, skip: set[str] | None = None) -> str:
    files = sorted(ROOT.glob("*.md"))
    if skip:
        files = [f for f in files if f.name not in skip]
    parts = [f"--- {f.name} ---\n{f.read_text(encoding='utf-8').strip()}" for f in files]
    return "\n\n".join(parts)
