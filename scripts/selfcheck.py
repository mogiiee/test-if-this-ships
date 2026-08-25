#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from groundskeeper.context_load import load_grass_context
from groundskeeper.core_fetch import parse_core_version_from_package_json
from groundskeeper.env import Settings
from groundskeeper.pipeline import count_files_in_diff, format_review_markdown, pick_review_model
from groundskeeper.types import PipelineOut, ReviewResult, TriageResult


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
    assert "coding-rules.md" in grass
    assert "try/catch" in grass
    assert "originalRequest" in grass

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
    assert "No material findings" in md
    assert "review_tier: `triage`" in md

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
    print("selfcheck ok")


if __name__ == "__main__":
    main()
