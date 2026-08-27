import re
from typing import Literal

Command = Literal["review", "deep", "override", "teach", "help"]
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
    if low == "" or re.match(r"^(help|commands|\?)\b", low):
        return "help", ""
    if re.match(r"^(deep(\s+review)?|review\s+deep)\b", low):
        return "deep", ""
    if re.match(r"^review\b", low):
        return "review", ""
    if re.match(r"^(override|overwrite|approve)\b", low):
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


def help_body(rules_url: str) -> str:
    return (
        "## if this ships\n\n"
        "QdRepo's reviewer for appointment-bridge PRs.\n\n"
        "- `@if-this-ships review` — review this PR\n"
        "- `@if-this-ships deep review` — flag every issue (no cap): security, selectors, core/node mismatch, unused code, what ships\n"
        "- `@if-this-ships teach …` — I'll remember it and use it on the next review\n"
        "- `@if-this-ships override` — you think I'm wrong; I'll approve anyway\n\n"
        f"Current rules: {rules_url}\n\n"
        "To update any of these rules, contact @mogiiee."
    )


def file_names_from_diff(diff: str) -> list[str]:
    return re.findall(r"^diff --git a/.+ b/(.+)$", diff, flags=re.M)


def estimate_review_seconds(file_count: int, *, deep: bool) -> int:
    # ponytail: comment ETA only; Opus wall time varies. Bump constants if comments undershoot.
    n = max(file_count, 1)
    if deep:
        return min(240, 75 + 25 * n)
    return min(120, 30 + 12 * n)


def format_eta(seconds: int) -> str:
    if seconds < 45:
        return f"about {seconds} seconds"
    minutes = max(1, round(seconds / 60))
    return "about 1 min" if minutes == 1 else f"about {minutes} minutes"


def progress_body(
    elapsed_s: int,
    *,
    files: list[str] | None = None,
    eta_s: int | None = None,
    deep: bool = False,
) -> str:
    kind = "Deep review" if deep else "Review"
    eta = f" {format_eta(eta_s).capitalize()}." if eta_s else ""
    looking = ""
    if files:
        shown = files[:15]
        extra = f" (+{len(files) - 15} more)" if len(files) > 15 else ""
        looking = "\n\nFiles: " + ", ".join(f"`{f}`" for f in shown) + extra
    if elapsed_s <= 0:
        return f"## if this ships\n\n{kind} under process.{eta}{looking}"
    return f"## if this ships\n\nStill reviewing after {elapsed_s} seconds.{eta}{looking}"
