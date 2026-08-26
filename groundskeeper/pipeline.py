import re

import httpx

from groundskeeper.claude import complete_json, extract_json
from groundskeeper.context_load import load_grass_context
from groundskeeper.core_fetch import (
    fetch_core_snapshot,
    format_core_for_prompt,
    parse_core_version_from_package_json,
)
from groundskeeper.env import get_settings
from groundskeeper.learned import load_learned
from groundskeeper.types import Finding, PipelineOut, PrBundle, ReviewResult, TriageResult

SEVERITY_RANK = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_HEADING = {
    "blocker": "Blockers",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_RANK.get(f.severity, 9), f.path or ""))


def review_event(review: ReviewResult) -> str:
    if review.clean or not review.findings:
        return "APPROVE"
    if any(f.severity in {"blocker", "high"} for f in review.findings):
        return "REQUEST_CHANGES"
    return "APPROVE"


def format_finding_line(f: Finding) -> str:
    loc = f"`{f.path}:{f.line}`" if f.path and f.line else (f"`{f.path}`" if f.path else "")
    title = f"{f.always_flag or f.type}"
    where = f" in {loc}" if loc else ""
    bits = [f"**{title}**{where}", f.why]
    if f.fix_direction:
        bits.append(f"Fix: {f.fix_direction}")
    return "\n\n".join(bits)


def format_inline_body(f: Finding) -> str:
    return format_finding_line(f)


def count_files_in_diff(diff: str) -> int:
    n = len(re.findall(r"^diff --git ", diff, flags=re.M))
    return n if n else (1 if diff.strip() else 0)


def pick_review_model(triage: TriageResult, settings) -> tuple[str, str]:
    """
    Always triage first (caller). Never jump straight to Sonnet.
    - deep (Opus): multiple files OR complete flow OR triage.deep_review
    - sonnet: single-file (or small) but triage says use_sonnet
    - triage model: small one-file change; triage handles the review
    """
    if triage.files_changed >= 2 or triage.complete_flow or triage.deep_review:
        return settings.model_opus, "deep"
    if triage.use_sonnet:
        return settings.model_sonnet, "sonnet"
    return settings.model_triage, "triage"


async def run_review_pipeline(github_token: str, pr: PrBundle) -> PipelineOut:
    settings = get_settings()
    grass = load_grass_context()
    learned = await load_learned(github_token, pr.owner, pr.repo)
    if learned:
        grass += "\n\n--- learned.md ---\n" + learned
    file_count = count_files_in_diff(pr.diff)

    core_version = (
        parse_core_version_from_package_json(pr.package_json) if pr.package_json else None
    )

    core_prompt = "Core version not found in package.json."
    if core_version:
        async with httpx.AsyncClient(
            timeout=120,
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "if-this-ships",
            },
        ) as client:
            snap = await fetch_core_snapshot(client, core_version)
            core_prompt = format_core_for_prompt(snap)

    triage_user = f"""PR: {pr.owner}/{pr.repo}#{pr.number}
Title: {pr.title}
Files changed (from diff): {file_count}

Diff (may be truncated):
{pr.diff[:60_000]}

You are TRIAGE only. You do not skip. Return JSON only:
{{
  "files_changed": {file_count},
  "complete_flow": boolean,
  "deep_review": boolean,
  "use_sonnet": boolean,
  "reason": string,
  "risk_signals": string[],
  "touched_helpers": string[]
}}

Rules for your flags:
- complete_flow=true if the change alters a whole appointment path (auth/verify/create/change/cancel/logout/response routing), not a tiny local edit.
- deep_review=true if multiple files OR complete_flow OR systemic cross-helper risk. (Pipeline also forces deep when files_changed >= 2.)
- use_sonnet=true ONLY when deep_review is false AND a single-file change still needs more than a cheap pass (non-trivial logic). For tiny one-file edits, use_sonnet=false so triage model does the review.
- Prefer deep_review=false and use_sonnet=false for simple one-file changes."""

    triage_text, triage_model = complete_json(
        model=settings.model_triage,
        system="if this ships triage. JSON only. Never assume Sonnet runs by default.",
        user=triage_user,
        max_tokens=1024,
    )
    triage = TriageResult.model_validate(extract_json(triage_text))
    triage.files_changed = file_count  # trust the diff count
    if file_count >= 2:
        triage.deep_review = True
    if triage.complete_flow:
        triage.deep_review = True

    review_model, review_tier = pick_review_model(triage, settings)

    review_user = f"""You are if this ships, an internal teammate reviewing an appointment-bridge PR.

Default is approve and shut up. Only speak when the diff *literally* breaks a hard rule.

Hyperbrowser is a brand-new isolated browser every job. Never warn about leftover login sessions.

## Rules (from context/)
{grass}

## Core at {core_version or "unknown"}
{core_prompt}

## PR
{pr.owner}/{pr.repo}#{pr.number}
Title: {pr.title}
Body:
{pr.body or "(empty)"}

Triage: {triage.model_dump_json()}
Review tier: {review_tier}

## Diff
{pr.diff[:100_000]}

## Output rules
- Return JSON only matching:
{{
  "summary": string,
  "change_class": "flow_change"|"refactor"|"feature"|"bugfix"|"html"|"config"|"test"|"other",
  "flows_touched": string[],
  "clean": boolean,
  "findings": [
    {{
      "type": "blatant"|"flow_impact"|"hyperbrowser_risk"|"contract"|"info",
      "severity": "blocker"|"high"|"medium"|"low",
      "path": string optional,
      "line": number optional,
      "flows": string[],
      "intent": string,
      "if_ships": string,
      "why": string,
      "fix_direction": string,
      "suggestion": string optional,
      "always_flag": string optional
    }}
  ]
}}
- Prefer clean=true and findings=[]. That is the correct answer for a reasonable helper PR.
- Do not stretch always-flag-these. No try/catch in the diff → do not mention try/catch. Same for every other item.
- Do not flag incomplete wiring, portal copy guesses, missing REQ_OPT_NOT_FOUND, networkidle, AuditError for missing fields, or "bridge only has logout".
- summary: one Slack sentence.
- why / if_ships / fix_direction: one sentence each. No paragraphs.
- At most 3 findings. Drop the rest.
- suggestion only for a tiny patch.
- Worst first: blocker, high, medium, low."""

    review_text, review_model_used = complete_json(
        model=review_model,
        system="if this ships: sparse. Approve when nothing is blatantly broken. JSON only. Two sentences max per finding. Do not invent work.",
        user=review_user,
        max_tokens=4096,
    )
    review = ReviewResult.model_validate(extract_json(review_text))
    if review.clean:
        review.findings = []
    else:
        review.findings = sort_findings(review.findings)

    return PipelineOut(
        triage=triage,
        review=review,
        core_version=core_version,
        models={"triage": triage_model, "review": review_model_used},
        review_tier=review_tier,
    )


def format_review_markdown(out: PipelineOut) -> str:
    review = out.review
    lines = [
        "## if this ships",
        "",
        review.summary.strip(),
    ]
    if review.clean or not review.findings:
        lines += ["", "Nothing here that would break a job. Approved."]
        return "\n".join(lines)

    current = None
    for f in sort_findings(review.findings):
        heading = SEVERITY_HEADING.get(f.severity, f.severity)
        if heading != current:
            current = heading
            lines += ["", f"### {heading}", ""]
        lines.append(format_finding_line(f))
        if f.suggestion:
            lines += ["", "```suggestion", f.suggestion, "```"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
