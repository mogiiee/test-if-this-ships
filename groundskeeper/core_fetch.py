import base64
import re

import httpx

from groundskeeper.env import get_settings

_CORE_DEP = re.compile(r"""appt-bridge-core["']\s*:\s*["']([^"']+)["']""")

CORE_PATHS = [
    "src/coreLambdaHandler.ts",
    "src/baseAppointmentBridge.ts",
    "src/interfaces/appointmentBridge.ts",
    "src/utils/requestFormatter.ts",
    "src/utils/asyncUtils.ts",
    "src/utils/errorClassifier.ts",
    "src/models/auditError.ts",
    "src/models/verifyResult.ts",
    "src/models/appointmentResult.ts",
    "src/enums/errorType.ts",
    "ERROR_CLASSIFICATION_GUIDE.md",
]


def parse_core_version_from_package_json(pkg_json: str) -> str | None:
    m = _CORE_DEP.search(pkg_json)
    if not m:
        return None
    spec = m.group(1)
    if "#" in spec:
        return spec.rsplit("#", 1)[-1].removeprefix("refs/tags/")
    semver = re.search(r"v?\d+\.\d+\.\d+", spec)
    if not semver:
        return None
    v = semver.group(0)
    return v if v.startswith("v") else f"v{v}"


async def fetch_core_snapshot(client: httpx.AsyncClient, version: str) -> dict:
    settings = get_settings()
    owner, repo = settings.core_repo.split("/", 1)
    files: list[dict[str, str]] = []
    for path in CORE_PATHS:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        r = await client.get(url, params={"ref": version})
        if r.status_code != 200:
            continue  # ponytail: skip missing paths across older tags
        data = r.json()
        content_b64 = data.get("content")
        if data.get("type") == "file" and content_b64:
            files.append(
                {
                    "path": path,
                    "content": base64.b64decode(content_b64).decode("utf-8"),
                }
            )
    return {"version": version, "files": files}


def format_core_for_prompt(snapshot: dict, max_chars: int = 80_000) -> str:
    settings = get_settings()
    out = f"Core repo {settings.core_repo} @ {snapshot['version']}\n\n"
    for f in snapshot["files"]:
        chunk = f"### {f['path']}\n```ts\n{f['content']}\n```\n\n"
        if len(out) + len(chunk) > max_chars:
            out += f"\n[truncated remaining core files at {max_chars} chars]\n"
            break
        out += chunk
    return out
