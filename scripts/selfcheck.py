#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from groundskeeper.commands import (
    estimate_review_seconds,
    file_names_from_diff,
    help_body,
    parse_mention,
    progress_body,
)
from groundskeeper.context_load import load_grass_context
from groundskeeper.core_fetch import parse_core_version_from_package_json
from groundskeeper.env import Settings
from groundskeeper.pipeline import (
    count_files_in_diff,
    format_review_markdown,
    pick_review_model,
    prompt_diff,
    review_event,
    sort_findings,
)
from groundskeeper.types import Finding, PipelineOut, ReviewResult, TriageResult


def main() -> None:
    pkg = """{
      "dependencies": {
        "appt-bridge-core": "git+https://<GH_TOKEN>@github.com/QdRepo/appt_bridge_core.git#v1.0.59"
      }
    }"""
    assert parse_core_version_from_package_json(pkg) == "v1.0.59"

    grass = load_grass_context()
    assert "always-flag-these.md" in grass
    assert "how-we-review.md" in grass
    deep_grass = load_grass_context(skip={"how-we-review.md"})
    assert "how-we-review.md" not in deep_grass
    assert "always-flag-these.md" in deep_grass
    assert "coding-rules.md" in grass
    assert "try/catch" in grass
    assert "originalRequest" in grass
    assert "already-logged-in" in grass or "already logged in" in grass
    assert "if this ships" in grass.lower()

    assert parse_mention("@if-this-ships review", "if-this-ships") == ("review", "")
    assert parse_mention("if-this-ships review", "if-this-ships") == ("review", "")
    assert parse_mention("@if this ships review", "if-this-ships") == ("review", "")
    assert parse_mention("@if-this-ships deep review", "if-this-ships") == ("deep", "")
    assert parse_mention("@if-this-ships deep", "if-this-ships") == ("deep", "")
    assert parse_mention("@if-this-ships review deep", "if-this-ships") == ("deep", "")
    assert parse_mention("@if-this-ships", "if-this-ships") == ("help", "")
    assert parse_mention("@if-this-ships help", "if-this-ships") == ("help", "")
    assert parse_mention("@if-this-ships override", "if-this-ships") == ("override", "")
    assert parse_mention("@if-this-ships overwrite", "if-this-ships") == ("override", "")
    assert parse_mention("@if-this-ships /teach don't warn about sessions", "if-this-ships") == (
        "teach",
        "don't warn about sessions",
    )
    assert parse_mention("looks fine", "if-this-ships") == (None, "")
    from groundskeeper.commands import parse_scope, strip_scope
    from groundskeeper.learned import filter_learned, quoted_lesson

    assert parse_scope("all bridges") == "all"
    assert parse_scope("this bridge") == "this"
    assert parse_scope("only this") == "this"
    assert parse_scope("@if-this-ships all bridges", "if-this-ships") == "all"
    assert parse_scope("never fake REQUESTED for all bridges", trailing=True) == "all"
    assert parse_scope("this helper should use AuditError", trailing=True) is None
    assert parse_scope(
        "for all bridges, it is okay if the package has the token"
    ) == "all"
    assert parse_scope("it is okay if the package has the token") is None
    assert strip_scope("never fake REQUESTED for all bridges") == "never fake REQUESTED"
    stripped = strip_scope(
        "for all bridges, it is okay if the package has the token"
    )
    assert "package" in stripped
    assert "all bridges" not in stripped.lower()
    assert quoted_lesson("Learning this now.\n\n> never fake REQUESTED\n\nIs this") == (
        "never fake REQUESTED"
    )
    learned_doc = """# Learned

## 2026-08-26 — a/b#1
**Scope:** all bridges
global rule

## 2026-08-26 — a/other#2
**Scope:** only `a/other`
other only

## 2026-08-26 — a/b#3
**Scope:** only `a/b`
this only
"""
    filtered = filter_learned(learned_doc, "a", "b")
    assert "global rule" in filtered
    assert "this only" in filtered
    assert "other only" not in filtered
    from groundskeeper.learned import learn_marker
    import base64
    import json

    marker = learn_marker("never fake REQUESTED", "this", "a/b", "a/b#3")
    assert marker.startswith("<!-- if-this-ships-learn ")
    payload = json.loads(base64.b64decode(marker.split()[2].encode()).decode())
    assert payload["lesson"] == "never fake REQUESTED"
    assert payload["scope"] == "this"
    assert "Review under process." in progress_body(0)
    assert "15 seconds" in progress_body(15)
    assert "30 seconds" in progress_body(30)
    assert "Deep review" in progress_body(0, deep=True, eta_s=120, files=["a.ts"])
    assert "`a.ts`" in progress_body(0, deep=True, eta_s=120, files=["a.ts"])
    assert "About" in progress_body(0, eta_s=90)
    assert file_names_from_diff(
        "diff --git a/x.ts b/x.ts\n+++ b/x.ts\ndiff --git a/y.ts b/y.ts\n"
    ) == ["x.ts", "y.ts"]
    assert estimate_review_seconds(1, deep=False) < estimate_review_seconds(8, deep=True)

    # routing: multi-file → deep
    settings = Settings()
    multi = TriageResult(files_changed=3, deep_review=False, use_sonnet=True)
    model, tier = pick_review_model(multi, settings)
    assert tier == "deep"
    assert model == settings.model_opus

    # single-file + use_sonnet → sonnet
    mid = TriageResult(files_changed=1, deep_review=False, use_sonnet=True)
    model, tier = pick_review_model(mid, settings)
    assert tier == "sonnet"

    # single-file simple → triage model (not sonnet, not deep)
    tiny = TriageResult(files_changed=1, deep_review=False, use_sonnet=False)
    model, tier = pick_review_model(tiny, settings)
    assert tier == "triage"
    assert model == settings.model_triage

    # complete flow → deep
    flow = TriageResult(files_changed=1, complete_flow=True, deep_review=True)
    _, tier = pick_review_model(flow, settings)
    assert tier == "deep"

    diff = "diff --git a/x.ts b/x.ts\n+++ b/x.ts\ndiff --git a/y.ts b/y.ts\n"
    assert count_files_in_diff(diff) == 2
    noisy = (
        "diff --git a/package-lock.json b/package-lock.json\n"
        + ("+lock\n" * 50)
        + "diff --git a/src/helpers/verificationHelper.ts b/src/helpers/verificationHelper.ts\n"
        "+throw new AuditError('x')\n"
    )
    shown = prompt_diff(noisy, 100_000)
    assert "verificationHelper.ts" in shown
    assert "+lock" not in shown
    assert "omitted 1 lockfile" in shown
    from groundskeeper.github_client import diff_from_pr_files

    assembled = diff_from_pr_files(
        [
            {"filename": "package-lock.json", "patch": "+lock"},
            {"filename": "src/helpers/verificationHelper.ts", "patch": "@@ -1 +1 @@\n+ok"},
        ]
    )
    assert "verificationHelper.ts" in assembled
    assert "+lock" not in assembled
    assert "omitted 1 lockfile" in assembled

    clean = PipelineOut(
        triage=TriageResult(files_changed=1, reason="tiny"),
        review=ReviewResult(
            summary="Looks grounded.",
            change_class="html",
            clean=True,
            findings=[],
        ),
        core_version="v1.0.59",
        models={"triage": "haiku", "review": "haiku"},
        review_tier="triage",
    )
    md = format_review_markdown(clean)
    assert "if this ships" in md
    assert "Groundskeeper" not in md
    assert "Approved" in md

    parsed = ReviewResult.model_validate(
        {
            "summary": "Found try/catch",
            "change_class": "bugfix",
            "flows_touched": ["verify"],
            "clean": False,
            "findings": [
                {
                    "type": "blatant",
                    "severity": "blocker",
                    "path": "src/helpers/verificationHelper.ts",
                    "line": 40,
                    "flows": ["verify"],
                    "intent": "catch UI errors",
                    "if_ships": "ErrorClassifier never sees the real failure",
                    "why": "try/catch swallows message-based classification",
                    "fix_direction": "Remove try/catch; throw AuditError or let it propagate",
                    "always_flag": "no try/catch in helpers",
                }
            ],
        }
    )
    assert parsed.findings[0].always_flag == "no try/catch in helpers"
    low = Finding(
        type="info",
        severity="low",
        path="a.ts",
        line=1,
        intent="n",
        if_ships="n",
        why="n",
        fix_direction="n",
    )
    high = parsed.findings[0]
    assert [f.severity for f in sort_findings([low, high])] == ["blocker", "low"]
    dirty = ReviewResult(
        summary="bad",
        change_class="bugfix",
        clean=False,
        findings=[high],
    )
    assert review_event(dirty) == "REQUEST_CHANGES"
    assert review_event(clean.review) == "APPROVE"
    low_only = ReviewResult(
        summary="Nits only.",
        change_class="other",
        clean=False,
        findings=[low],
    )
    assert review_event(low_only) == "APPROVE"
    low_md = format_review_markdown(
        PipelineOut(
            triage=TriageResult(files_changed=1, reason="tiny"),
            review=low_only,
            core_version="v1.0.59",
            models={"triage": "haiku", "review": "haiku"},
            review_tier="triage",
        )
    )
    assert "Approved" in low_md
    assert "low notes" in low_md
    help_md = help_body("https://github.com/mogiiee/test-if-this-ships/tree/main/context")
    assert "@if-this-ships teach" in help_md
    assert "@if-this-ships override" in help_md
    assert "@if-this-ships review" in help_md
    assert "deep review" in help_md
    assert "mogiiee" in help_md
    assert "QdRepo" in help_md
    assert "https://github.com/mogiiee/test-if-this-ships/tree/main/context" in help_md
    from scripts.apply_learn import parse_learn_env

    assert parse_learn_env({"LEARN_JSON": "null", "COMMENT_BODY": ""}) is None
    parsed = parse_learn_env(
        {"LEARN_JSON": json.dumps({"lesson": "no try/catch", "scope": "this", "source": "a/b#1"})}
    )
    assert parsed is not None
    assert parsed["lesson"] == "no try/catch"
    print("selfcheck ok")


if __name__ == "__main__":
    main()
