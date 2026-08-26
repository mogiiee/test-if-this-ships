import hashlib
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from groundskeeper.commands import parse_mention
from groundskeeper.env import get_settings
from groundskeeper.review_runner import override_pr, review_pr, teach_from_comment

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("if-this-ships")

app = FastAPI(title="if this ships", version="0.1.0")


class ReviewRequest(BaseModel):
    owner: str
    repo: str
    number: int
    installation_id: int | None = Field(default=None, alias="installationId")

    model_config = {"populate_by_name": True}


def _verify_signature(secret: str, body: bytes, signature: str | None) -> None:
    if not secret:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(400, "missing signature")
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={digest}", signature):
        raise HTTPException(400, "bad signature")


def _is_bot(user: dict | None) -> bool:
    return (user or {}).get("type") == "Bot"


@app.get("/health")
async def health():
    s = get_settings()
    return {
        "ok": True,
        "name": "if-this-ships",
        "githubApp": s.has_github_app(),
        "hasPat": bool(s.github_token),
    }


def _queue_command(
    background: BackgroundTasks,
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
    body: str,
    about: str = "",
    who: str = "developer",
    in_reply_to: int | None = None,
) -> dict:
    settings = get_settings()
    if not number:
        return {"ok": True, "skipped": "no pr number"}
    cmd, rest = parse_mention(body, settings.bot_login)
    if cmd == "review":
        background.add_task(review_pr, installation_id, owner, repo, number)
        return {"ok": True, "queued": "review"}
    if cmd == "override":
        background.add_task(override_pr, installation_id, owner, repo, number, who)
        return {"ok": True, "queued": "override"}
    if cmd == "teach":
        if not rest:
            return {"ok": True, "skipped": "empty teach"}
        background.add_task(
            teach_from_comment,
            installation_id,
            owner,
            repo,
            number,
            rest,
            about,
            in_reply_to,
        )
        return {"ok": True, "queued": "teach"}
    return {"ok": True, "skipped": "no command"}


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    body = await request.body()
    settings = get_settings()
    _verify_signature(settings.github_webhook_secret, body, x_hub_signature_256)
    payload = await request.json()
    installation_id = (payload.get("installation") or {}).get("id")
    repo = payload.get("repository") or {}
    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")

    if x_github_event == "issue_comment" and payload.get("action") == "created":
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        if issue.get("pull_request") is None:
            return {"ok": True, "skipped": "not a pr"}
        if _is_bot(comment.get("user")):
            return {"ok": True, "skipped": "bot"}
        return _queue_command(
            background,
            installation_id,
            owner,
            name,
            issue["number"],
            comment.get("body") or "",
            who=(comment.get("user") or {}).get("login") or "developer",
        )

    if x_github_event == "pull_request_review_comment" and payload.get("action") == "created":
        comment = payload.get("comment") or {}
        if _is_bot(comment.get("user")):
            return {"ok": True, "skipped": "bot"}
        pr = payload.get("pull_request") or {}
        return _queue_command(
            background,
            installation_id,
            owner,
            name,
            pr.get("number"),
            comment.get("body") or "",
            who=(comment.get("user") or {}).get("login") or "developer",
            in_reply_to=comment.get("in_reply_to_id"),
        )

    if x_github_event == "pull_request_review" and payload.get("action") == "submitted":
        review = payload.get("review") or {}
        user = review.get("user") or {}
        if _is_bot(user):
            return {"ok": True, "skipped": "bot"}
        if (review.get("state") or "").lower() != "approved":
            return {"ok": True, "skipped": "not an approve"}
        pr = payload.get("pull_request") or {}
        background.add_task(
            override_pr,
            installation_id,
            owner,
            name,
            pr.get("number"),
            user.get("login") or "developer",
        )
        return {"ok": True, "queued": "human-approve"}

    return {"ok": True, "ignored": x_github_event}


@app.post("/review")
async def manual_review(req: ReviewRequest, background: BackgroundTasks):
    background.add_task(
        review_pr,
        req.installation_id,
        req.owner,
        req.repo,
        req.number,
    )
    return {"ok": True, "queued": True}


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "groundskeeper.app:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )
