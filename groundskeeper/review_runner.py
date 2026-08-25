import asyncio
import logging
import re

from groundskeeper.env import get_settings
from groundskeeper.github_client import (
    core_token,
    load_pr_bundle,
    post_inline_comments,
    post_pr_comment,
    resolve_token,
)
from groundskeeper.pipeline import format_review_markdown, run_review_pipeline

log = logging.getLogger("groundskeeper")


def mention_triggers_review(body: str) -> bool:
    settings = get_settings()
    bot = re.escape(settings.bot_login)
    if not re.search(rf"@{bot}\b", body, flags=re.I):
        return False
    if re.search(r"\breview\b", body, flags=re.I):
        return True
    return bool(re.fullmatch(rf"@{bot}\s*", body.strip(), flags=re.I))


async def review_pr(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
) -> None:
    token = await resolve_token(installation_id)
    await post_pr_comment(token, owner, repo, number, "**Groundskeeper** is walking the PR…")

    bundle = await load_pr_bundle(token, owner, repo, number)
    out = await run_review_pipeline(core_token(token), bundle)
    await post_pr_comment(token, owner, repo, number, format_review_markdown(out))

    inline = []
    for f in out.review.findings:
        if not (f.path and f.line):
            continue
        parts = [
            f"**[{f.severity}] {f.type}**",
            f"Always flag: {f.always_flag}" if f.always_flag else None,
            f"If this ships: {f.if_ships}",
            f"Why: {f.why}",
            f"Fix: {f.fix_direction}",
            f"\n```suggestion\n{f.suggestion}\n```" if f.suggestion else None,
        ]
        inline.append(
            {
                "path": f.path,
                "line": f.line,
                "body": "\n".join(p for p in parts if p),
            }
        )
    if inline:
        await post_inline_comments(
            token, owner, repo, number, bundle.head_sha, inline
        )


def schedule_review(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
) -> None:
    # ponytail: fire-and-forget after webhook ack; ceiling = single process. Upgrade: queue.
    asyncio.create_task(
        _safe_review(installation_id, owner, repo, number),
        name=f"review-{owner}-{repo}-{number}",
    )


async def _safe_review(
    installation_id: int | None,
    owner: str,
    repo: str,
    number: int,
) -> None:
    try:
        await review_pr(installation_id, owner, repo, number)
    except Exception:
        log.exception("review failed for %s/%s#%s", owner, repo, number)
