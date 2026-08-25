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
from groundskeeper.types import PipelineOut, PrBundle, ReviewResult, TriageResult


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
                "User-Agent": "groundskeeper",
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
        system="Groundskeeper triage. JSON only. Never assume Sonnet runs by default.",
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

    review_user = f"""You are Groundskeeper reviewing an internal appointment-bridge PR.

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
- If nothing material: clean=true and findings=[].
- Anything in always-flag-these.md → finding with always_flag set.
- Flow changes without a bug → type flow_impact is OK.
- Do not invent nits. Point; don't rewrite the PR.
- suggestion only for small concrete patches."""

    review_text, review_model_used = complete_json(
        model=review_model,
        system="Groundskeeper: sparse, consequence-first bridge reviewer. JSON only. Silence when clean.",
        user=review_user,
        max_tokens=8192,
    )
    review = ReviewResult.model_validate(extract_json(review_text))
    if review.clean:
        review.findings = []

    return PipelineOut(
        triage=triage,
        review=review,
        core_version=core_version,
        models={"triage": triage_model, "review": review_model_used},
        review_tier=review_tier,
    )


def format_review_markdown(out: PipelineOut) -> str:
    settings = get_settings()
    review, triage = out.review, out.triage
    lines = [
        "## Groundskeeper",
        "",
        review.summary,
        "",
        "<details><summary>meta</summary>",
        "",
        f"- change_class: `{review.change_class}`",
        f"- flows: {', '.join(f'`{f}`' for f in review.flows_touched) or '—'}",
        f"- files_changed: `{triage.files_changed}`",
        f"- review_tier: `{out.review_tier}` (triage → deep|sonnet|triage)",
        f"- core: `{out.core_version or 'not found'}` (`{settings.core_repo}`)",
        f"- models: triage `{out.models['triage']}`, review `{out.models['review']}`",
        f"- why this tier: {triage.reason or 'n/a'}",
        "",
        "</details>",
    ]
    if review.clean or not review.findings:
        lines += ["", "_No material findings. Looks grounded._"]
        return "\n".join(lines)

    lines.append("")
    for i, f in enumerate(review.findings, start=1):
        loc = (
            f"`{f.path}:{f.line}`"
            if f.path and f.line
            else (f"`{f.path}`" if f.path else "general")
        )
        lines.append(f"### {i}. [{f.severity}] {f.type} — {loc}")
        if f.always_flag:
            lines.append(f"**Always flag:** {f.always_flag}")
        if f.flows:
            lines.append(f"**Flows:** {', '.join(f.flows)}")
        lines.append(f"**Intent:** {f.intent}")
        lines.append(f"**If this ships:** {f.if_ships}")
        lines.append(f"**Why:** {f.why}")
        lines.append(f"**Fix direction:** {f.fix_direction}")
        if f.suggestion:
            lines += ["", "Suggestion:", "```suggestion", f.suggestion, "```"]
        lines.append("")
    return "\n".join(lines)
