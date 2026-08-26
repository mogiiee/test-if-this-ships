from datetime import datetime, timezone

from groundskeeper.env import get_settings
from groundskeeper.github_client import get_repo_file, put_repo_file

HEADER = "# Learned\n\nNotes the team taught @if-this-ships. Treat these as rules on the next review.\n"


def _repo_parts() -> tuple[str, str, str] | None:
    settings = get_settings()
    raw = (settings.learned_repo or "").strip()
    if "/" not in raw:
        return None
    owner, repo = raw.split("/", 1)
    return owner, repo, settings.learned_path


async def load_learned(token: str) -> str:
    loc = _repo_parts()
    if not loc:
        return ""
    owner, repo, path = loc
    text, _sha = await get_repo_file(token, owner, repo, path)
    return (text or "").strip()


async def append_learned(
    token: str,
    lesson: str,
    *,
    about: str = "",
    source: str = "",
) -> None:
    loc = _repo_parts()
    if not loc or not lesson.strip():
        return
    owner, repo, path = loc
    current, sha = await get_repo_file(token, owner, repo, path)
    if not (current or "").strip():
        current = HEADER
    if not current.endswith("\n"):
        current += "\n"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = f"\n## {now} — {source or 'teach'}\n"
    if about.strip():
        block += f"About: {about.strip()}\n"
    block += f"{lesson.strip()}\n"
    await put_repo_file(
        token,
        owner,
        repo,
        path,
        current + block,
        sha,
        f"teach: {source or 'review comment'}",
    )
