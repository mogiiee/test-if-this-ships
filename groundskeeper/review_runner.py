import asyncio
import logging

from groundskeeper.commands import parse_mention, parse_scope, progress_body, strip_scope
from groundskeeper.env import get_settings
from groundskeeper.github_client import (
    core_token,
    get_review_comment,
    learned_access_token,
    list_issue_comments,
    load_pr_bundle,
    post_pr_comment,
    resolve_token,
    submit_pr_review,
    update_pr_comment,
)
from groundskeeper.learned import (
    LEARNED_MARK,
    LEARNING_MARK,
    append_learned,
    learned_comment,
    quoted_lesson,
)
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


def _is_our_comment(user: dict | None) -> bool:
    login = ((user or {}).get("login") or "").lower()
    return get_settings().bot_login.lower() in login


async def _pending_teach_comment(
    token: str, owner: str, repo: str, number: int
) -> tuple[int, str] | None:
    comments = await list_issue_comments(token, owner, repo, number)
    for comment in reversed(comments):
        if not _is_our_comment(comment.get("user")):
            continue
        body = comment.get("body") or ""
        if LEARNED_MARK in body:
            return None
        if LEARNING_MARK in body:
            lesson = quoted_lesson(body)
            if lesson:
                return int(comment["id"]), lesson
            return None
    return None


async def _save_lesson(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
    lesson: str,
    scope: str,
    about: str = "",
    comment_id: int | None = None,
    announce_scope: bool = True,
) -> None:
    install_token = await resolve_token(installation_id)
    source = f"{owner}/{repo}#{number}"
    write_token = await learned_access_token(install_token)
    try:
        await append_learned(
            write_token,
            lesson,
            scope=scope,
            bridge=f"{owner}/{repo}",
            about=about,
            source=source,
        )
    except Exception:
        log.exception("could not persist lesson to learned.md")
        fail = (
            "## if this ships\n\n"
            "I heard you but could not save the note. Try teaching again."
        )
        if comment_id:
            await update_pr_comment(install_token, owner, repo, comment_id, fail)
        else:
            await post_pr_comment(install_token, owner, repo, number, fail)
        return
    body = learned_comment(
        lesson,
        scope,
        owner,
        repo,
        source=source,
        about=about,
        announce_scope=announce_scope,
    )
    if comment_id:
        await update_pr_comment(install_token, owner, repo, comment_id, body)
    else:
        await post_pr_comment(install_token, owner, repo, number, body)


async def teach_from_comment(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
    lesson: str,
    about: str = "",
    in_reply_to: int | None = None,
) -> None:
    settings = get_settings()
    explicit = parse_scope(lesson, settings.bot_login)
    scope = explicit or "all"
    lesson = strip_scope(lesson).strip()
    if not lesson:
        token = await resolve_token(installation_id)
        await post_pr_comment(
            token,
            owner,
            repo,
            number,
            "## if this ships\n\nTell me what to remember.",
        )
        return
    install_token = await resolve_token(installation_id)
    token = settings.github_token or install_token
    if in_reply_to:
        try:
            parent = await get_review_comment(token, owner, repo, in_reply_to)
            about = (parent.get("body") or about)[:500]
        except Exception:
            log.exception("could not load parent review comment %s", in_reply_to)
    await _save_lesson(
        installation_id,
        owner,
        repo,
        number,
        lesson,
        scope,
        about=about,
        announce_scope=explicit is not None,
    )


async def finish_pending_teach(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
    scope: str,
) -> None:
    token = await resolve_token(installation_id)
    pending = await _pending_teach_comment(token, owner, repo, number)
    if not pending:
        return
    comment_id, lesson = pending
    await _save_lesson(
        installation_id,
        owner,
        repo,
        number,
        lesson,
        scope,
        comment_id=comment_id,
    )
