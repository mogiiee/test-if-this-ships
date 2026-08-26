import asyncio
import logging

from groundskeeper.commands import parse_mention, progress_body
from groundskeeper.env import get_settings
from groundskeeper.github_client import (
    core_token,
    get_review_comment,
    load_pr_bundle,
    post_pr_comment,
    resolve_token,
    submit_pr_review,
    update_pr_comment,
)
from groundskeeper.learned import append_learned
from groundskeeper.pipeline import (
    format_inline_body,
    format_review_markdown,
    review_event,
    run_review_pipeline,
    sort_findings,
)

log = logging.getLogger("if-this-ships")


def mention_triggers_review(body: str) -> bool:
    settings = get_settings()
    cmd, _ = parse_mention(body, settings.bot_login)
    return cmd == "review"


async def review_pr(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
) -> None:
    token = await resolve_token(installation_id)
    comment_id = await post_pr_comment(
        token, owner, repo, number, progress_body(0)
    )
    finished = asyncio.Event()

    async def heartbeat() -> None:
        elapsed = 0
        while True:
            try:
                await asyncio.wait_for(finished.wait(), timeout=15)
                return
            except TimeoutError:
                if finished.is_set():
                    return
                elapsed += 15
                try:
                    await update_pr_comment(
                        token, owner, repo, comment_id, progress_body(elapsed)
                    )
                except Exception:
                    log.exception("progress comment update failed")

    ticker = asyncio.create_task(heartbeat())
    try:
        bundle = await load_pr_bundle(token, owner, repo, number)
        out = await run_review_pipeline(core_token(token), bundle)
        event = review_event(out.review)
        body = format_review_markdown(out)
        inline = [
            {"path": f.path, "line": f.line, "body": format_inline_body(f)}
            for f in sort_findings(out.review.findings)
            if f.path and f.line
        ]
        finished.set()
        await ticker
        await update_pr_comment(token, owner, repo, comment_id, body)
        await submit_pr_review(
            token, owner, repo, number, bundle.head_sha, event, body, inline
        )
    except Exception:
        finished.set()
        ticker.cancel()
        try:
            await update_pr_comment(
                token,
                owner,
                repo,
                comment_id,
                "## if this ships\n\nReview failed. Check the service logs.",
            )
        except Exception:
            log.exception("could not mark progress comment as failed")
        raise
    finally:
        finished.set()
        if not ticker.done():
            ticker.cancel()


async def override_pr(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
    who: str = "developer",
) -> None:
    token = await resolve_token(installation_id)
    bundle = await load_pr_bundle(token, owner, repo, number)
    await submit_pr_review(
        token,
        owner,
        repo,
        number,
        bundle.head_sha,
        "APPROVE",
        f"## if this ships\n\n{who} overrode the review. Treating this as approved.",
        [],
    )


async def teach_from_comment(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
    lesson: str,
    about: str = "",
    in_reply_to: int | None = None,
) -> None:
    if not lesson.strip():
        return
    settings = get_settings()
    install_token = await resolve_token(installation_id)
    token = settings.github_token or install_token
    if in_reply_to:
        try:
            parent = await get_review_comment(token, owner, repo, in_reply_to)
            about = (parent.get("body") or about)[:500]
        except Exception:
            log.exception("could not load parent review comment %s", in_reply_to)
    source = f"{owner}/{repo}#{number}"
    try:
        await append_learned(token, lesson, about=about, source=source)
    except Exception:
        log.exception("teach via PAT failed; trying installation token")
        await append_learned(install_token, lesson, about=about, source=source)
    await post_pr_comment(
        install_token,
        owner,
        repo,
        number,
        "Got it — saved. I'll use that on the next review.",
    )
