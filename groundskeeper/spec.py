import re

import httpx

from groundskeeper.github_client import _headers
from groundskeeper.types import PrBundle

_HASH = re.compile(r"(?:^|[^\w/])#(\d+)\b")
_ISSUE_URL = re.compile(
    r"github\.com/[^/\s]+/[^/\s]+/issues/(\d+)", re.I
)
_CLOSING_ONLY = re.compile(
    r"^(?:\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+\s*)+$",
    re.I,
)
_MAX_ISSUES = 3
_MAX_CHARS = 8000


def issue_numbers(title: str, body: str, *, pr_number: int) -> list[int]:
    """Issue ids mentioned in the PR, excluding the PR's own number."""
    seen: list[int] = []
    for match in (*_ISSUE_URL.finditer(f"{title}\n{body}"), *_HASH.finditer(f"{title}\n{body}")):
        n = int(match.group(1))
        if n == pr_number or n in seen:
            continue
        seen.append(n)
        if len(seen) >= _MAX_ISSUES:
            break
    return seen


def pr_body_as_spec(body: str) -> str:
    text = (body or "").strip()
    if not text or _CLOSING_ONLY.match(text):
        return ""
    return text[:_MAX_CHARS]


def format_spec_prompt(issue_blobs: list[str], pr_body: str) -> str:
    parts = [b.strip() for b in issue_blobs if b.strip()]
    extra = pr_body_as_spec(pr_body)
    if extra:
        parts.append(f"PR body:\n{extra}")
    return "\n\n".join(parts)


async def load_spec_text(token: str, pr: PrBundle) -> str:
    nums = issue_numbers(pr.title, pr.body, pr_number=pr.number)
    blobs: list[str] = []
    if nums:
        async with httpx.AsyncClient(timeout=30) as client:
            for n in nums:
                r = await client.get(
                    f"https://api.github.com/repos/{pr.owner}/{pr.repo}/issues/{n}",
                    headers=_headers(token),
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                if data.get("pull_request"):
                    continue
                title = (data.get("title") or "").strip()
                body = (data.get("body") or "").strip()[:_MAX_CHARS]
                blobs.append(f"Issue #{n}: {title}\n{body}".strip())
    return format_spec_prompt(blobs, pr.body)
