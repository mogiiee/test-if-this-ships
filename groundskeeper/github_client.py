import base64
import time

import httpx
import jwt

from groundskeeper.env import get_settings
from groundskeeper.types import PrBundle


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "if-this-ships",
    }


def app_jwt() -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": settings.github_app_id}
    return jwt.encode(payload, settings.normalized_private_key(), algorithm="RS256")


async def installation_token(installation_id: int) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                **_headers(app_jwt()),
                "Accept": "application/vnd.github+json",
            },
        )
        r.raise_for_status()
        return r.json()["token"]


async def resolve_token(installation_id: int | None = None) -> str:
    settings = get_settings()
    if installation_id and settings.has_github_app():
        return await installation_token(installation_id)
    if settings.github_token:
        return settings.github_token
    raise RuntimeError("Need GITHUB_APP_* + installation_id, or GITHUB_TOKEN")


def core_token(fallback: str) -> str:
    settings = get_settings()
    return settings.github_token or fallback


async def load_pr_bundle(token: str, owner: str, repo: str, number: int) -> PrBundle:
    async with httpx.AsyncClient(timeout=120) as client:
        pr_r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
            headers=_headers(token),
        )
        pr_r.raise_for_status()
        pr = pr_r.json()

        diff_r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
            headers={**_headers(token), "Accept": "application/vnd.github.diff"},
        )
        diff_r.raise_for_status()

        package_json = None
        pkg_r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/package.json",
            headers=_headers(token),
            params={"ref": pr["head"]["sha"]},
        )
        if pkg_r.status_code == 200:
            data = pkg_r.json()
            if data.get("type") == "file" and data.get("content"):
                package_json = base64.b64decode(data["content"]).decode("utf-8")

    return PrBundle(
        owner=owner,
        repo=repo,
        number=number,
        title=pr.get("title") or "",
        body=pr.get("body") or "",
        head_sha=pr["head"]["sha"],
        diff=diff_r.text,
        package_json=package_json,
    )


async def post_pr_comment(token: str, owner: str, repo: str, number: int, body: str) -> int:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments",
            headers=_headers(token),
            json={"body": body},
        )
        r.raise_for_status()
        return int(r.json()["id"])


async def update_pr_comment(
    token: str, owner: str, repo: str, comment_id: int, body: str
) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.patch(
            f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}",
            headers=_headers(token),
            json={"body": body},
        )
        r.raise_for_status()


async def get_review_comment(token: str, owner: str, repo: str, comment_id: int) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/comments/{comment_id}",
            headers=_headers(token),
        )
        r.raise_for_status()
        return r.json()


async def submit_pr_review(
    token: str,
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    event: str,
    body: str,
    comments: list[dict] | None = None,
) -> None:
    payload: dict = {"commit_id": head_sha, "event": event, "body": body}
    trimmed = [c for c in (comments or []) if c.get("path") and c.get("line")][:12]
    if trimmed:
        payload["comments"] = [
            {"path": c["path"], "line": c["line"], "body": c["body"]} for c in trimmed
        ]
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews",
            headers=_headers(token),
            json=payload,
        )
        r.raise_for_status()


async def get_repo_file(
    token: str, owner: str, repo: str, path: str
) -> tuple[str, str | None]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=_headers(token),
        )
        if r.status_code == 404:
            return "", None
        r.raise_for_status()
        data = r.json()
        if data.get("type") != "file" or not data.get("content"):
            return "", data.get("sha")
        return base64.b64decode(data["content"]).decode("utf-8"), data.get("sha")


async def put_repo_file(
    token: str,
    owner: str,
    repo: str,
    path: str,
    content: str,
    sha: str | None,
    message: str,
) -> None:
    payload: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=_headers(token),
            json=payload,
        )
        r.raise_for_status()
