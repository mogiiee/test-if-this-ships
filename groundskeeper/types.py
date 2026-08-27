from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    type: Literal["blatant", "flow_impact", "hyperbrowser_risk", "contract", "security", "info"]
    severity: Literal["blocker", "high", "medium", "low"]
    path: str | None = None
    line: int | None = None
    flows: list[str] = Field(default_factory=list)
    intent: str
    if_ships: str
    why: str
    fix_direction: str
    suggestion: str | None = None
    # Which item from context/always-flag-these.md this hits (if any)
    always_flag: str | None = None


class ReviewResult(BaseModel):
    summary: str
    change_class: Literal[
        "flow_change",
        "refactor",
        "feature",
        "bugfix",
        "html",
        "config",
        "test",
        "other",
    ]
    flows_touched: list[str] = Field(default_factory=list)
    clean: bool
    findings: list[Finding] = Field(default_factory=list)


class TriageResult(BaseModel):
    """Triage never skips. It chooses the next model tier."""

    files_changed: int = 0
    complete_flow: bool = False
    # True → deep review (Opus). Forced on by pipeline when files_changed >= 2.
    deep_review: bool = False
    # Only used when deep_review is false: whether Sonnet is worth it vs triage model alone.
    use_sonnet: bool = False
    reason: str = ""
    risk_signals: list[str] = Field(default_factory=list)
    touched_helpers: list[str] = Field(default_factory=list)


class PrBundle(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str = ""
    head_sha: str
    diff: str
    package_json: str | None = None


class PipelineOut(BaseModel):
    triage: TriageResult
    review: ReviewResult
    core_version: str | None
    models: dict[str, str]
    review_tier: str  # triage | sonnet | deep
