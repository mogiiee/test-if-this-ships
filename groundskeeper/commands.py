import re
from typing import Literal

Command = Literal["review", "override", "teach"]
Scope = Literal["all", "this"]

_ALL = re.compile(
    r"\b(?:for\s+)?(?:all(?:\s+appointment)?\s+bridges|every\s+bridge|all of them)\b",
    re.I,
)
_THIS = re.compile(
    r"\b(?:for\s+)?(?:this(?:\s+particular)?(?:\s+one)?\s+bridge|only this(?:\s+one|\s+bridge)?|this repo)\b",
    re.I,
)


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


def parse_scope(body: str, bot_login: str = "", *, trailing: bool = False) -> Scope | None:
    text = body
    if bot_login:
        text = re.sub(_mention_pattern(bot_login), " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    low = text.lower()
    this_pat = _THIS.pattern + r"\s*[.!]?\s*$" if trailing else _THIS.pattern
    all_pat = _ALL.pattern + r"\s*[.!]?\s*$" if trailing else _ALL.pattern
    has_this = bool(re.search(this_pat, low, flags=re.I) or (not trailing and re.fullmatch(r"this", low)))
    has_all = bool(re.search(all_pat, low, flags=re.I) or (not trailing and re.fullmatch(r"all", low)))
    if has_this:
        return "this"
    if has_all:
        return "all"
    return None


def strip_scope(lesson: str) -> str:
    text = _ALL.sub(" ", lesson)
    text = _THIS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" .,-")


def progress_body(elapsed_s: int) -> str:
    if elapsed_s <= 0:
        return "## if this ships\n\nReview under process."
    return f"## if this ships\n\nStill reviewing after {elapsed_s} seconds."
