import hashlib
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from groundskeeper.env import get_settings
from groundskeeper.review_runner import mention_triggers_review, review_pr

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("groundskeeper")

app = FastAPI(title="Groundskeeper", version="0.1.0")


class ReviewRequest(BaseModel):
    owner: str
    repo: str
    number: int
    installation_id: int | None = Field(default=None, alias="installationId")

    model_config = {"populate_by_name": True}


def _verify_signature(secret: str, body: bytes, signature: str | None) -> None:
    if not secret:
        return  # local/dev without App secret
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(400, "missing signature")
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={digest}", signature):
        raise HTTPException(400, "bad signature")


@app.get("/health")
async def health():
    s = get_settings()
    return {
        "ok": True,
        "name": "groundskeeper",
        "githubApp": s.has_github_app(),
        "hasPat": bool(s.github_token),
    }


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

    if x_github_event == "issue_comment" and payload.get("action") == "created":
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        if issue.get("pull_request") is None:
            return {"ok": True, "skipped": "not a pr"}
        if (comment.get("user") or {}).get("type") == "Bot":
            return {"ok": True, "skipped": "bot"}
        if not mention_triggers_review(comment.get("body") or ""):
            return {"ok": True, "skipped": "no mention"}

        repo = payload["repository"]
        installation_id = (payload.get("installation") or {}).get("id")
        # BackgroundTasks is safer than create_task across request lifecycle
        background.add_task(
            review_pr,
            installation_id,
            repo["owner"]["login"],
            repo["name"],
            issue["number"],
        )
        return {"ok": True, "queued": True}

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
