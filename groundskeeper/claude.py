import json
import re

import anthropic

from groundskeeper.env import get_settings


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
    return text, model


def extract_json(text: str) -> object:
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = (fenced.group(1) if fenced else text).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON object in model response")
    return json.loads(raw[start : end + 1])
