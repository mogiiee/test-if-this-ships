import re
from typing import Literal

Command = Literal["review", "override", "teach"]


def _mention_pattern(bot_login: str) -> str:
    slug = re.escape(bot_login)
    spaced = re.escape(bot_login.replace("-", " "))
    return rf"@?(?:{slug}|{spaced})\b"


def parse_mention(body: str, bot_login: str) -> tuple[Command | None, str]:
    """Return (command, leftover text) if the bot is addressed."""
    mention = _mention_pattern(bot_login)
    if not re.search(mention, body, flags=re.I):
        return None, ""
    rest = re.sub(mention, " ", body, flags=re.I)
    rest = re.sub(r"\s+", " ", rest).strip()
    rest = rest.lstrip("/").strip()
    low = rest.lower()
    if low == "" or re.match(r"^review\b", low):
        return "review", ""
    if re.match(r"^(override|approve)\b", low):
        return "override", ""
    if re.match(r"^(teach|learn)(\s+this)?\b", low):
        lesson = re.sub(r"^(teach|learn)(\s+this)?\b[:\s-]*", "", rest, count=1, flags=re.I).strip()
        return "teach", lesson
    return None, rest


def progress_body(elapsed_s: int) -> str:
    if elapsed_s <= 0:
        return "## if this ships\n\nReview under process."
    return f"## if this ships\n\nStill reviewing after {elapsed_s} seconds."
