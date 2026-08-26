import base64
import json
import re
from datetime import datetime, timezone

from groundskeeper.env import get_settings
from groundskeeper.github_client import get_repo_file, put_repo_file

HEADER = "# Learned\n\nNotes the team taught @if-this-ships. Treat these as rules on the next review.\n"
LEARNING_MARK = "Learning this now."
LEARNED_MARK = "I have learned this."


def _repo_parts() -> tuple[str, str, str] | None:
    settings = get_settings()
    raw = (settings.learned_repo or "").strip()
    if "/" not in raw:
        return None
    owner, repo = raw.split("/", 1)
    return owner, repo, settings.learned_path


def block_applies(block: str, owner: str, repo: str) -> bool:
    m = re.search(r"\*\*Scope:\*\*\s*(.+)", block)
    if not m:
        return True
    scope = m.group(1).strip().lower()
    if scope.startswith("all"):
        return True
    return f"{owner}/{repo}".lower() in scope


def filter_learned(text: str, owner: str, repo: str) -> str:
    if not (text or "").strip():
        return ""
    chunks = re.split(r"(?m)^(?=## )", text)
    keep = [chunks[0]]
    keep.extend(c for c in chunks[1:] if block_applies(c, owner, repo))
    return "".join(keep).strip()


def quoted_lesson(body: str) -> str:
    lines = []
    for line in body.splitlines():
        if line.startswith("> "):
            lines.append(line[2:])
        elif line.startswith(">"):
            lines.append(line[1:].lstrip())
        elif lines:
            break
    return "\n".join(lines).strip()


def learning_comment(lesson: str, owner: str, repo: str) -> str:
    return (
        "## if this ships\n\n"
        f"{LEARNING_MARK}\n\n"
        f"> {lesson.strip()}\n\n"
        f"Is this for **all appointment bridges**, or only **this one** (`{owner}/{repo}`)? "
        "Reply `all bridges` or `this bridge`."
    )


def learn_marker(
    lesson: str,
    scope: str,
    bridge: str,
    source: str,
    about: str = "",
) -> str:
    payload = json.dumps(
        {
            "lesson": lesson.strip(),
            "scope": scope,
            "bridge": bridge,
            "source": source,
            "about": about,
        },
        separators=(",", ":"),
    )
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return f"<!-- if-this-ships-learn {b64} -->"


def learned_comment(
    lesson: str,
    scope: str,
    owner: str,
    repo: str,
    source: str = "",
    about: str = "",
) -> str:
    where = (
        "I'll apply this to **all appointment bridges**."
        if scope == "all"
        else f"I'll only use this on `{owner}/{repo}`."
    )
    marker = learn_marker(
        lesson, scope, f"{owner}/{repo}", source or f"{owner}/{repo}", about
    )
    return (
        f"## if this ships\n\n{LEARNED_MARK}\n\n{where}\n\n"
        f"> {lesson.strip()}\n\n{marker}\n"
    )


async def load_learned(token: str, owner: str = "", repo: str = "") -> str:
    loc = _repo_parts()
    if not loc:
        return ""
    learned_owner, learned_repo, path = loc
    text, _sha = await get_repo_file(token, learned_owner, learned_repo, path)
    text = (text or "").strip()
    if not text or not owner:
        return text
    return filter_learned(text, owner, repo)


async def append_learned(
    token: str,
    lesson: str,
    *,
    scope: str,
    bridge: str,
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
    scope_line = (
        "**Scope:** all bridges"
        if scope == "all"
        else f"**Scope:** only `{bridge}`"
    )
    block = f"\n## {now} — {source or 'teach'}\n{scope_line}\n"
    if about.strip():
        block += f"About: {about.strip()}\n"
    block += f"{lesson.strip()}\n"
    try:
        await put_repo_file(
            token,
            owner,
            repo,
            path,
            current + block,
            sha,
            f"teach: {source or 'review comment'}",
        )
    except Exception:
        # ponytail: one retry on SHA clash; two simultaneous teaches still lose one
        current, sha = await get_repo_file(token, owner, repo, path)
        if not (current or "").strip():
            current = HEADER
        if not current.endswith("\n"):
            current += "\n"
        await put_repo_file(
            token,
            owner,
            repo,
            path,
            current + block,
            sha,
            f"teach: {source or 'review comment'}",
        )
