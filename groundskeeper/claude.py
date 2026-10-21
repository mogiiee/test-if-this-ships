import json
import logging
import re

import anthropic

from groundskeeper.env import get_settings

log = logging.getLogger("if-this-ships")

# Appended when the first reply is truncated or not a usable review.
COMPACT_JSON_RETRY = (
    "\n\nYour previous JSON was cut off. Return one JSON object only. "
    "Omit suggestion. One short sentence per string. Close every string."
)


def _sts_identity_token() -> str:
    import boto3

    settings = get_settings()
    sts = boto3.client("sts", region_name=settings.aws_region or "us-east-1")
    try:
        resp = sts.get_web_identity_token(
            Audience=["https://api.anthropic.com"],
            SigningAlgorithm="RS256",
            DurationSeconds=900,
        )
    except AttributeError as e:
        raise RuntimeError(
            "boto3 is too old for sts:GetWebIdentityToken. Upgrade boto3."
        ) from e
    except Exception as e:
        raise RuntimeError(f"sts:GetWebIdentityToken failed: {e}") from e
    token = resp.get("WebIdentityToken")
    if not token:
        raise RuntimeError("sts:GetWebIdentityToken returned no token")
    return token


def anthropic_client():
    settings = get_settings()
    if settings.has_anthropic_wif():
        from anthropic import WorkloadIdentityCredentials

        return anthropic.Anthropic(
            credentials=WorkloadIdentityCredentials(
                identity_token_provider=_sts_identity_token,
                federation_rule_id=settings.anthropic_federation_rule_id,
                organization_id=settings.anthropic_organization_id,
                service_account_id=settings.anthropic_service_account_id,
                workspace_id=settings.anthropic_workspace_id or None,
            )
        )
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "Need Anthropic WIF (ANTHROPIC_FEDERATION_RULE_ID, "
            "ANTHROPIC_ORGANIZATION_ID, ANTHROPIC_SERVICE_ACCOUNT_ID) "
            "or ANTHROPIC_API_KEY"
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def complete_json(*, model: str, system: str, user: str, max_tokens: int = 4096) -> tuple[str, str]:
    text, stop = _message(model=model, system=system, user=user, max_tokens=max_tokens)
    if stop == "max_tokens":
        log.warning("model output truncated at max_tokens")
    try:
        extract_json(text)
    except ValueError:
        log.warning("model JSON unusable (stop=%s); retrying compact", stop)
        text, _stop = _message(
            model=model,
            system=system,
            user=user + COMPACT_JSON_RETRY,
            max_tokens=max_tokens,
        )
    return text, model


def _message(*, model: str, system: str, user: str, max_tokens: int) -> tuple[str, str]:
    client = anthropic_client()
    try:
        res = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError(
            "Anthropic rejected the identity. Check WIF (issuer, audience, "
            "role ARN) or ANTHROPIC_API_KEY."
        ) from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic {e.status_code}: {e.message}") from e
    except anthropic.APIError as e:
        raise RuntimeError(f"Anthropic error: {e}") from e
    text = "".join(b.text for b in res.content if getattr(b, "type", None) == "text")
    return text, getattr(res, "stop_reason", None) or ""


def extract_json(text: str) -> object:
    """Parse model JSON. Repair bad backslashes, then keep a closed prefix if cut off."""
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = (fenced.group(1) if fenced else text).strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError("No JSON object in model response")
    body = _repair_escapes(raw[start:])
    end = body.rfind("}")
    err: json.JSONDecodeError | None = None
    if end >= 0:
        try:
            return json.loads(body[: end + 1])
        except json.JSONDecodeError as e:
            err = e
    try:
        data = json.loads(_close_truncated(body))
    except (json.JSONDecodeError, ValueError):
        if err is not None and "Unterminated string" in err.msg:
            raise ValueError("model JSON was cut off") from err
        raise ValueError("No JSON object in model response") from err
    log.warning("closed a truncated model JSON object")
    return data


def _repair_escapes(raw: str) -> str:
    """Double backslashes that are not JSON escapes (\\s, \\., paths).

    Valid escapes stay: \\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX.
    """
    out: list[str] = []
    in_str = False
    i = 0
    n = len(raw)
    changed = False
    while i < n:
        ch = raw[i]
        if not in_str:
            if ch == '"':
                in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = False
            out.append(ch)
            i += 1
            continue
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = raw[i + 1] if i + 1 < n else ""
        if nxt == "u" and i + 6 <= n and all(c in "0123456789abcdefABCDEF" for c in raw[i + 2 : i + 6]):
            out.append(raw[i : i + 6])
            i += 6
            continue
        if nxt in '"\\/bfnrt':
            out.append(ch)
            out.append(nxt)
            i += 2
            continue
        out.append("\\\\")
        changed = True
        i += 1
    if changed:
        log.warning("repaired invalid JSON escapes in model output")
    return "".join(out)


def _close_truncated(raw: str) -> str:
    """Drop the open string at EOF and close the object that was already written.

    A `}` inside that open string is not a closer. Cutting there is what made
    json.loads report an unterminated string.
    """
    cut = _open_string_at_end(raw)
    if cut is None:
        raise ValueError("No JSON object in model response")
    head = _drop_incomplete_tail(raw[:cut])
    if "{" not in head:
        raise ValueError("No JSON object in model response")
    return _balance(head)


def _open_string_at_end(raw: str) -> int | None:
    in_str = False
    esc = False
    start = 0
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            start = i
    return start if in_str else None


def _drop_incomplete_tail(head: str) -> str:
    t = head.rstrip()
    while True:
        if t.endswith(":"):
            t = _drop_trailing_string(t[:-1].rstrip()).rstrip()
            continue
        # Drop an empty `{` left by the cut-off finding. Leave `[` so it closes as [].
        if t.endswith(",") or t.endswith("{"):
            t = t[:-1].rstrip()
            continue
        break
    return t


def _drop_trailing_string(s: str) -> str:
    t = s.rstrip()
    if not t.endswith('"'):
        return t
    i = len(t) - 2
    while i >= 0:
        if t[i] == '"':
            slashes = 0
            j = i - 1
            while j >= 0 and t[j] == "\\":
                slashes += 1
                j -= 1
            if slashes % 2 == 0:
                return t[:i]
        i -= 1
    return t


def _balance(s: str) -> str:
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()
    s = s.rstrip()
    if s.endswith(","):
        s = s[:-1]
    return s + "".join(reversed(stack))
