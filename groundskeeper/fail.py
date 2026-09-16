import re

import httpx

_SECRET = re.compile(
    r"(sk-ant-[^\s]+|github_pat_[^\s]+|ghp_[^\s]+|gho_[^\s]+|ghu_[^\s]+)"
)


def fail_body(action: str, err: BaseException) -> str:
    """PR-visible failure. Named action, no log dump, no secrets."""
    title = {
        "review": "Review failed.",
        "teach": "I heard you but could not save the note.",
        "help": "Could not post help.",
        "override": "Could not override.",
    }.get(action, "Failed.")
    return f"## if this ships\n\n{title}\n\n{explain_fail(err)}"


def _blob(err: BaseException) -> str:
    parts = [f"{type(err).__name__}: {err}"]
    cause = err.__cause__
    if cause is not None:
        parts.append(f"{type(cause).__name__}: {cause}")
    return _SECRET.sub("[redacted]", " ".join(parts))


def _http_status(err: BaseException) -> int | None:
    cur: BaseException | None = err
    while cur is not None:
        if isinstance(cur, httpx.HTTPStatusError):
            return cur.response.status_code
        cur = cur.__cause__
    return None


def explain_fail(err: BaseException) -> str:
    raw = _blob(err)
    low = raw.lower()
    status = _http_status(err)

    if "api key is invalid" in low or "anthropic api key" in low or "authentication_error" in low:
        return (
            "Anthropic rejected the identity. Check the Console federation rule "
            "(issuer, audience, role ARN) or `ANTHROPIC_API_KEY`."
        )
    if "need anthropic wif" in low or "an anthropic_api_key is required" in low or "anthropic_api_key is required" in low:
        return (
            "No Anthropic identity is set. Use AWS WIF "
            "(`ANTHROPIC_FEDERATION_RULE_ID`) or `ANTHROPIC_API_KEY`."
        )
    if "outboundwebidentityfederationdisabled" in low or "outbound web identity federation" in low:
        return "AWS outbound web identity federation is off in this account."
    if "sts:getwebidentitytoken" in low or "getwebidentitytoken" in low:
        return "The App Runner role cannot mint an STS identity token."
    if "resource not accessible by integration" in low:
        return (
            "The GitHub App cannot access that resource. "
            "Install it on the PR repo and on `LEARNED_REPO`."
        )
    if "required status" in low:
        return (
            "GitHub blocked the write (branch protection). "
            "Taught notes belong in the notes repo, not protected main."
        )
    if "learned_repo is not set" in low:
        return "Taught-notes repo is not configured. Set `LEARNED_REPO`."
    if "need github_app" in low or "need github_token" in low:
        return (
            "The bot has no GitHub credentials. "
            "Set the GitHub App or `GITHUB_TOKEN` on the service."
        )
    if "no json object" in low:
        return "The model returned text that was not JSON. Retry the review."
    if "validation error" in low:
        return "The model returned a review that did not match the schema. Retry the review."
    if "timed out" in low or "timeout" in low or "timedout" in low:
        return "The review timed out talking to GitHub or the model. Retry."
    if status == 401 or "github 401" in low:
        return "GitHub rejected the token. Check the App installation and credentials."
    if status == 404 or "github 404" in low:
        return "GitHub could not find that PR, file, or repo."
    if status == 429 or "rate limit" in low:
        return "GitHub rate-limited the bot. Retry in a minute."
    if status == 422 or "github 422" in low:
        return "GitHub rejected the review payload. Retry the review."
    if status in {500, 502, 503} or "github 50" in low:
        return "GitHub is failing. Retry."
    if status == 403 or "github 403" in low:
        return (
            "GitHub forbade that action. "
            "Check App permissions and that it is installed on the notes repo."
        )
    if "check the service logs" in low:
        return (
            "The review failed internally. Retry; "
            "if it keeps happening, the service is misconfigured."
        )
    return raw[:500]
