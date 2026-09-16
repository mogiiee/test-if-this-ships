#!/usr/bin/env python3
"""Stress the reviewer. Fails the process if anything is wrong.

Covers commands, teaching, core versions, lockfiles, and every failure
model we know. Network is mocked unless you pass --live.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from groundskeeper.commands import (  # noqa: E402
    estimate_review_seconds,
    file_names_from_diff,
    help_body,
    parse_mention,
    parse_scope,
    progress_body,
    strip_scope,
)
from groundskeeper.core_fetch import (  # noqa: E402
    fetch_core_snapshot,
    format_core_for_prompt,
    parse_core_version_from_package_json,
)
from groundskeeper.env import Settings  # noqa: E402
from groundskeeper.fail import explain_fail, fail_body  # noqa: E402
from groundskeeper.github_client import (  # noqa: E402
    diff_from_pr_files,
    submit_pr_review,
)
from groundskeeper.learned import (  # noqa: E402
    append_learned,
    filter_learned,
    learn_marker,
    learned_comment,
    load_learned,
    quoted_lesson,
)
from groundskeeper.pipeline import (  # noqa: E402
    format_review_markdown,
    pick_review_model,
    prompt_diff,
    review_event,
    run_review_pipeline,
    sort_findings,
)
from groundskeeper.review_runner import (  # noqa: E402
    help_pr,
    override_pr,
    review_pr,
    teach_from_comment,
)
from groundskeeper.types import (  # noqa: E402
    Finding,
    PipelineOut,
    PrBundle,
    ReviewResult,
    TriageResult,
)
from scripts.apply_learn import parse_learn_env  # noqa: E402

BOT = "if-this-ships"
FAILURES: list[str] = []

TRIAGE_OK = {
    "files_changed": 1,
    "complete_flow": False,
    "deep_review": False,
    "use_sonnet": False,
    "reason": "tiny",
    "risk_signals": [],
    "touched_helpers": [],
}
REVIEW_OK = {
    "summary": "Looks grounded.",
    "change_class": "other",
    "flows_touched": [],
    "clean": True,
    "findings": [],
}


def check(name: str, fn) -> None:
    try:
        fn()
        print(f"  ok  {name}")
    except Exception:
        print(f"  FAIL {name}")
        traceback.print_exc()
        FAILURES.append(name)


def acheck(name: str, fn) -> None:
    check(name, lambda: asyncio.run(fn()))


def pkg(spec: str) -> str:
    return json.dumps({"dependencies": {"appt-bridge-core": spec}})


def pr_bundle(*, version: str | None = "v1.0.64", diff: str | None = None) -> PrBundle:
    package = None if version is None else pkg(
        f"git+https://github.com/QdRepo/appt_bridge_core.git#{version}"
    )
    return PrBundle(
        owner="QdRepo",
        repo="appt_sys_stress",
        number=23,
        title="stress",
        body="",
        head_sha="abc123",
        diff=diff
        or "diff --git a/src/helpers/verificationHelper.ts b/src/helpers/verificationHelper.ts\n"
        "+ok\n",
        package_json=package,
    )


def fake_settings(**kw) -> Settings:
    data = dict(
        anthropic_api_key="sk-ant-test",
        github_token="gho_test",
        github_webhook_secret="whsec",
        github_app_id="1",
        github_app_private_key="k",
        learned_repo="QdRepo/if-this-ships-notes",
        learned_path="learned.md",
        learned_ref="main",
        bot_login=BOT,
        core_repo="QdRepo/appt_bridge_core",
    )
    data.update(kw)
    return Settings(**data)


class FakeResp:
    def __init__(self, status: int, text: str = "", data=None):
        self.status_code = status
        self.text = text
        self._data = data if data is not None else {}
        self.is_error = status >= 400

    def json(self):
        return self._data

    def raise_for_status(self) -> None:
        if self.is_error:
            req = httpx.Request("POST", "https://api.github.com/")
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=req,
                response=httpx.Response(self.status_code, text=self.text, request=req),
            )


class FakeClient:
    def __init__(self, responses: list[FakeResp]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        payload = kw.get("json")
        self.calls.append((url, None if payload is None else dict(payload)))
        if not self.responses:
            raise AssertionError(f"unexpected POST {url}")
        return self.responses.pop(0)

    async def get(self, url, **kw):
        self.calls.append((url, kw.get("params")))
        if not self.responses:
            raise AssertionError(f"unexpected GET {url}")
        return self.responses.pop(0)

    async def put(self, url, **kw):
        self.calls.append((url, kw.get("json")))
        if not self.responses:
            raise AssertionError(f"unexpected PUT {url}")
        return self.responses.pop(0)


def _assert_clean_fail(body: str, *needles: str) -> None:
    assert body.startswith("## if this ships"), body
    assert "Groundskeeper" not in body
    assert "check the service logs" not in body.lower()
    assert "sk-ant-" not in body
    assert "github_pat_" not in body
    assert "ghp_" not in body
    for n in needles:
        assert n in body, f"missing {n!r} in {body!r}"


def test_commands() -> None:
    cases = [
        ("@if-this-ships review", "review"),
        ("if-this-ships review", "review"),
        ("@if this ships review", "review"),
        ("@if-this-ships deep review", "deep"),
        ("@if-this-ships deep", "deep"),
        ("@if-this-ships review deep", "deep"),
        ("@if-this-ships", "help"),
        ("@if-this-ships help", "help"),
        ("@if-this-ships override", "override"),
        ("@if-this-ships overwrite", "override"),
        ("@if-this-ships approve", "override"),
    ]
    for body, cmd in cases:
        got, _ = parse_mention(body, BOT)
        assert got == cmd, (body, got)
    cmd, lesson = parse_mention("@if-this-ships teach don't warn about sessions", BOT)
    assert cmd == "teach" and "sessions" in lesson
    assert parse_mention("looks fine", BOT) == (None, "")
    help_md = help_body("https://github.com/QdRepo/if-this-ships-notes/blob/main/learned.md")
    for bit in (
        "@if-this-ships teach",
        "@if-this-ships override",
        "@if-this-ships review",
        "deep review",
        "mogiiee",
        "if-this-ships-notes",
    ):
        assert bit in help_md
    assert "Groundskeeper" not in help_md
    assert "Deep review" in progress_body(0, deep=True, eta_s=120, files=["a.ts"])
    assert estimate_review_seconds(1, deep=False) < estimate_review_seconds(8, deep=True)


def test_teach_scope() -> None:
    assert parse_scope("all bridges") == "all"
    assert parse_scope("this bridge") == "this"
    assert parse_scope("only this") == "this"
    assert parse_scope("it is okay if the package has the token") is None
    assert strip_scope("never fake REQUESTED for all bridges") == "never fake REQUESTED"
    assert quoted_lesson("Learning this now.\n\n> never fake REQUESTED\n\nIs this") == (
        "never fake REQUESTED"
    )
    doc = """# Learned

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
    filtered = filter_learned(doc, "a", "b")
    assert "global rule" in filtered
    assert "this only" in filtered
    assert "other only" not in filtered
    body = learned_comment("no try/catch", "all", "QdRepo", "appt_sys_chep")
    assert "I have learned this." in body
    assert "all appointment bridges" in body
    marker = learn_marker("no try/catch", "this", "a/b", "a/b#3")
    payload = json.loads(base64_payload(marker))
    assert payload["scope"] == "this"
    assert parse_learn_env({"LEARN_JSON": "null", "COMMENT_BODY": ""}) is None
    parsed = parse_learn_env(
        {"LEARN_JSON": json.dumps({"lesson": "no try/catch", "scope": "this"})}
    )
    assert parsed["lesson"] == "no try/catch"


def base64_payload(marker: str) -> bytes:
    import base64

    return base64.b64decode(marker.split()[2].encode())


def test_core_versions() -> None:
    assert parse_core_version_from_package_json(pkg(
        "git+https://<GH_TOKEN>@github.com/QdRepo/appt_bridge_core.git#v1.0.59"
    )) == "v1.0.59"
    assert parse_core_version_from_package_json(pkg(
        "git+https://github.com/QdRepo/appt_bridge_core.git#v1.0.64"
    )) == "v1.0.64"
    assert parse_core_version_from_package_json(pkg("1.0.61")) == "v1.0.61"
    assert parse_core_version_from_package_json(pkg(
        "git+https://github.com/QdRepo/appt_bridge_core.git#refs/tags/v1.0.59"
    )) == "v1.0.59"
    assert parse_core_version_from_package_json("{}") is None
    assert parse_core_version_from_package_json(pkg("latest")) is None
    empty = format_core_for_prompt({"version": "v1.0.59", "files": []})
    assert "v1.0.59" in empty
    fat = format_core_for_prompt(
        {
            "version": "v1.0.64",
            "files": [{"path": "src/x.ts", "content": "x" * 90_000}],
        },
        max_chars=80_000,
    )
    assert "v1.0.64" in fat
    assert "truncated" in fat


async def test_core_snapshot_skips_missing_on_old_tag() -> None:
    class Client:
        async def get(self, url, params=None):
            ref = (params or {}).get("ref")
            if "auditError.ts" in url and ref == "v1.0.59":
                return FakeResp(404, "missing")
            return FakeResp(
                200,
                data={
                    "type": "file",
                    "content": __import__("base64").b64encode(b"ok").decode(),
                },
            )

    with patch(
        "groundskeeper.core_fetch.get_settings",
        return_value=fake_settings(),
    ):
        snap = await fetch_core_snapshot(Client(), "v1.0.59")  # type: ignore[arg-type]
    assert snap["version"] == "v1.0.59"
    paths = [f["path"] for f in snap["files"]]
    assert "src/models/auditError.ts" not in paths
    assert paths, "older tags should still yield the files that exist"


def test_lockfiles_and_truncation() -> None:
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
    huge = "diff --git a/src/a.ts b/src/a.ts\n" + ("+x\n" * 80_000)
    cut = prompt_diff(huge, 1000)
    assert "[diff truncated]" in cut
    assembled = diff_from_pr_files(
        [
            {"filename": "package-lock.json", "patch": "+lock"},
            {
                "filename": "src/helpers/verificationHelper.ts",
                "patch": "@@ -1 +1 @@\n+ok",
            },
            {"filename": "yarn.lock", "patch": "+y"},
        ]
    )
    assert "verificationHelper.ts" in assembled
    assert "+lock" not in assembled
    assert "omitted 2 lockfile" in assembled
    assert file_names_from_diff(
        "diff --git a/x.ts b/x.ts\n+++ b/x.ts\ndiff --git a/y.ts b/y.ts\n"
    ) == ["x.ts", "y.ts"]


def test_review_events() -> None:
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
    med = low.model_copy(update={"severity": "medium"})
    high = low.model_copy(update={"severity": "high", "always_flag": "no try/catch"})
    clean = ReviewResult(summary="ok", change_class="other", clean=True, findings=[])
    assert review_event(clean) == "APPROVE"
    assert review_event(
        ReviewResult(summary="nits", change_class="other", clean=False, findings=[low])
    ) == "APPROVE"
    assert review_event(
        ReviewResult(summary="m", change_class="other", clean=False, findings=[med])
    ) == "APPROVE"
    assert review_event(
        ReviewResult(summary="bad", change_class="bugfix", clean=False, findings=[high])
    ) == "REQUEST_CHANGES"
    assert [f.severity for f in sort_findings([low, high])] == ["high", "low"]
    md = format_review_markdown(
        PipelineOut(
            triage=TriageResult(files_changed=1),
            review=ReviewResult(
                summary="Nits only.",
                change_class="other",
                clean=False,
                findings=[low],
            ),
            core_version="v1.0.59",
            models={"review": "haiku"},
            review_tier="triage",
        )
    )
    assert "Approved" in md and "low notes" in md
    assert "Groundskeeper" not in md
    settings = fake_settings()
    assert pick_review_model(TriageResult(files_changed=3), settings)[1] == "deep"
    assert pick_review_model(
        TriageResult(files_changed=1, use_sonnet=True), settings
    )[1] == "sonnet"
    assert pick_review_model(TriageResult(files_changed=1), settings)[1] == "triage"


def test_fail_models() -> None:
    cases: list[tuple[BaseException, str]] = [
        (
            RuntimeError("Anthropic API key is invalid. Update ANTHROPIC_API_KEY on the service."),
            "Anthropic rejected the identity",
        ),
        (RuntimeError("ANTHROPIC_API_KEY is required"), "No Anthropic identity is set"),
        (
            RuntimeError("sts:GetWebIdentityToken failed: AccessDenied"),
            "cannot mint an STS identity token",
        ),
        (
            RuntimeError("GitHub 403 writing learned.md: Resource not accessible by integration"),
            "cannot access that resource",
        ),
        (
            RuntimeError("required status checks have not succeeded"),
            "branch protection",
        ),
        (RuntimeError("LEARNED_REPO is not set"), "Taught-notes repo is not configured"),
        (
            RuntimeError("Need GITHUB_APP_* + installation_id, or GITHUB_TOKEN"),
            "no GitHub credentials",
        ),
        (ValueError("No JSON object in model response"), "was not JSON"),
        (
            RuntimeError("1 validation error for ReviewResult\nsummary\n  Field required"),
            "did not match the schema",
        ),
        (TimeoutError("timed out"), "timed out"),
        (RuntimeError("GitHub 401 submitting review: bad creds"), "rejected the token"),
        (RuntimeError("GitHub 404 writing learned.md"), "could not find"),
        (RuntimeError("GitHub 422 submitting review: invalid line"), "rejected the review payload"),
        (RuntimeError("GitHub 500 submitting review: boom"), "GitHub is failing"),
        (RuntimeError("GitHub 429: API rate limit exceeded"), "rate-limited"),
        (RuntimeError("GitHub 403 writing learned.md: forbidden"), "forbade that action"),
        (
            RuntimeError("Review failed. Check the service logs"),
            "failed internally",
        ),
    ]
    for err, needle in cases:
        body = fail_body("review", err)
        _assert_clean_fail(body, "Review failed.", needle)
    teach = fail_body("teach", RuntimeError("required status checks have not succeeded"))
    _assert_clean_fail(teach, "could not save the note", "branch protection")
    leak = fail_body(
        "review",
        RuntimeError("boom sk-ant-api03-SECRET github_pat_SECRET ghp_SECRET"),
    )
    _assert_clean_fail(leak, "[redacted]")
    req = httpx.Request("GET", "https://api.github.com/repos/x")
    http_err = httpx.HTTPStatusError(
        "nope",
        request=req,
        response=httpx.Response(404, request=req),
    )
    _assert_clean_fail(fail_body("review", http_err), "could not find")


async def _pipeline_with(complete, *, deep=False, bundle=None, learned="", spec=""):
    bundle = bundle or pr_bundle()

    async def no_core(*a, **k):
        return {"version": "v1.0.64", "files": []}

    async def notes(*a, **k):
        return learned

    async def spec_text(*a, **k):
        return spec

    with (
        patch("groundskeeper.pipeline.complete_json", complete),
        patch("groundskeeper.pipeline.fetch_core_snapshot", no_core),
        patch("groundskeeper.pipeline.load_learned", notes),
        patch("groundskeeper.pipeline.load_spec_text", spec_text),
        patch("groundskeeper.pipeline.learned_access_token", AsyncMock(return_value="t")),
        patch("groundskeeper.pipeline.get_settings", return_value=fake_settings()),
    ):
        return await run_review_pipeline("t", bundle, deep=deep)


def _json_complete(review=None, triage=None):
    calls = []

    def complete(*, model, system, user, max_tokens=4096):
        calls.append({"model": model, "system": system, "user": user, "max_tokens": max_tokens})
        if "TRIAGE only" in user:
            return json.dumps(triage or TRIAGE_OK), model
        return json.dumps(review or REVIEW_OK), model

    complete.calls = calls  # type: ignore[attr-defined]
    return complete


async def test_pipeline_versions_in_prompt() -> None:
    for version in ("v1.0.59", "v1.0.64"):
        complete = _json_complete()
        bundle = pr_bundle(version=version)
        out = await _pipeline_with(complete, bundle=bundle)
        assert out.core_version == version
        review_user = complete.calls[-1]["user"]
        assert f"Core at {version}" in review_user
        assert "TAUGHT NOTES" not in review_user
    missing = _json_complete()
    out = await _pipeline_with(missing, bundle=pr_bundle(version=None, diff="+x\n"))
    assert out.core_version is None
    assert "Core version not found" in missing.calls[-1]["user"]


async def test_pipeline_taught_notes_and_deep() -> None:
    complete = _json_complete()
    await _pipeline_with(
        complete,
        learned="## note\nGH token in lockfile is fine\n",
        spec="Issue #9: real UI logout\nLogout must click Sign out.",
    )
    user = complete.calls[-1]["user"]
    assert "TAUGHT NOTES" in user
    assert "GH token in lockfile is fine" in user
    assert "how-we-review.md" in user
    assert "Issue #9: real UI logout" in user
    assert "skip the Spec axis" not in user

    empty_spec = _json_complete()
    await _pipeline_with(empty_spec, spec="")
    assert "skip the Spec axis" in empty_spec.calls[-1]["user"]

    deep = _json_complete()
    out = await _pipeline_with(deep, deep=True)
    assert out.review_tier == "deep"
    assert out.models["triage"] == "skipped"
    assert len(deep.calls) == 1
    assert "how-we-review.md" in deep.calls[0]["user"]
    assert "DEEP review" in deep.calls[0]["user"]
    assert "No finding cap" in deep.calls[0]["user"] or "no cap" in deep.calls[0]["user"].lower()
    assert "Spec source" in deep.calls[0]["user"]


async def test_pipeline_failure_models() -> None:
    async def boom_kind(err):
        def complete(**k):
            raise err

        try:
            await _pipeline_with(complete)
        except Exception as e:
            return e
        raise AssertionError("pipeline should have failed")

    e = await boom_kind(
        RuntimeError("Anthropic API key is invalid. Update ANTHROPIC_API_KEY on the service.")
    )
    _assert_clean_fail(fail_body("review", e), "Anthropic rejected the identity")

    e = await boom_kind(RuntimeError("ANTHROPIC_API_KEY is required"))
    _assert_clean_fail(fail_body("review", e), "No Anthropic identity is set")

    def no_json(*, model, system, user, max_tokens=4096):
        if "TRIAGE only" in user:
            return json.dumps(TRIAGE_OK), model
        return "I am sorry, I cannot produce JSON today.", model

    try:
        await _pipeline_with(no_json)
        raise AssertionError("expected JSON failure")
    except Exception as err:
        _assert_clean_fail(fail_body("review", err), "was not JSON")

    def bad_schema(*, model, system, user, max_tokens=4096):
        if "TRIAGE only" in user:
            return json.dumps(TRIAGE_OK), model
        return json.dumps({"summary": "nope"}), model

    try:
        await _pipeline_with(bad_schema)
        raise AssertionError("expected schema failure")
    except Exception as err:
        _assert_clean_fail(fail_body("review", err), "did not match the schema")


async def test_submit_review_retries_without_inline_on_422() -> None:
    inner = FakeClient(
        [
            FakeResp(422, "Path line not part of the diff"),
            FakeResp(200, data={"id": 1}),
        ]
    )
    with patch("groundskeeper.github_client.httpx.AsyncClient", lambda *a, **k: inner):
        await submit_pr_review(
            "t",
            "o",
            "r",
            1,
            "sha",
            "APPROVE",
            "ok",
            [{"path": "a.ts", "line": 9, "body": "nope"}],
        )
    assert len(inner.calls) == 2
    assert "comments" in inner.calls[0][1]
    assert "comments" not in inner.calls[1][1]


async def test_submit_review_hard_fail_is_clean() -> None:
    inner = FakeClient([FakeResp(500, "boom")])
    with patch("groundskeeper.github_client.httpx.AsyncClient", lambda *a, **k: inner):
        try:
            await submit_pr_review("t", "o", "r", 1, "sha", "APPROVE", "ok", [])
        except Exception as err:
            _assert_clean_fail(fail_body("review", err), "GitHub is failing")
            return
    raise AssertionError("expected submit to fail")


async def test_review_pr_posts_clean_fail() -> None:
    posted: list[str] = []

    async def boom(*a, **k):
        raise RuntimeError(
            "Anthropic API key is invalid. Update ANTHROPIC_API_KEY on the service."
        )

    with (
        patch("groundskeeper.review_runner.resolve_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.load_pr_bundle", AsyncMock(return_value=pr_bundle())),
        patch(
            "groundskeeper.review_runner.post_pr_comment",
            AsyncMock(side_effect=lambda *a, **k: posted.append(a[-1] if a else k.get("body")) or 7),
        ),
        patch(
            "groundskeeper.review_runner.update_pr_comment",
            AsyncMock(side_effect=lambda *a, **k: posted.append(a[-1] if a else k.get("body"))),
        ),
        patch("groundskeeper.review_runner.delete_pr_comment", AsyncMock()),
        patch("groundskeeper.review_runner.run_review_pipeline", boom),
    ):
        try:
            await review_pr(1, "QdRepo", "appt_sys_e2openapi", 23)
        except RuntimeError:
            pass
        else:
            raise AssertionError("review_pr should re-raise after posting")
    fail = posted[-1]
    _assert_clean_fail(fail, "Review failed.", "Anthropic rejected the identity")
    assert "`RuntimeError" not in fail


async def test_review_pr_fails_before_progress_still_comments() -> None:
    posted: list[str] = []

    async def boom_load(*a, **k):
        raise RuntimeError("GitHub 404 submitting review: Not Found")

    with (
        patch("groundskeeper.review_runner.resolve_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.load_pr_bundle", boom_load),
        patch(
            "groundskeeper.review_runner.post_pr_comment",
            AsyncMock(side_effect=lambda *a, **k: posted.append(a[-1]) or 1),
        ),
        patch("groundskeeper.review_runner.update_pr_comment", AsyncMock()),
    ):
        try:
            await review_pr(1, "o", "r", 1)
        except RuntimeError:
            pass
    assert posted, "should comment even if the progress comment never went up"
    _assert_clean_fail(posted[-1], "could not find")


async def test_teach_persists_to_notes_repo() -> None:
    store = {"text": "# Learned\n", "sha": "1", "puts": []}

    async def get(token, owner, repo, path, ref="main"):
        assert f"{owner}/{repo}" == "QdRepo/if-this-ships-notes"
        return store["text"], store["sha"]

    async def put(token, owner, repo, path, content, sha, message, branch="main"):
        store["puts"].append({"branch": branch, "content": content, "message": message})
        store["text"] = content
        store["sha"] = "2"

    with (
        patch("groundskeeper.learned.get_settings", return_value=fake_settings()),
        patch("groundskeeper.learned.ensure_branch", AsyncMock()),
        patch("groundskeeper.learned.get_repo_file", get),
        patch("groundskeeper.learned.put_repo_file", put),
    ):
        await append_learned(
            "t",
            "GH token in package-lock.json is fine",
            scope="all",
            bridge="QdRepo/appt_sys_chep",
            source="QdRepo/appt_sys_chep#9",
        )
        loaded = await load_learned("t", "QdRepo", "appt_sys_e2openapi")
    assert store["puts"], "teach must write"
    assert store["puts"][0]["branch"] == "main"
    assert "GH token in package-lock.json is fine" in store["text"]
    assert "**Scope:** all bridges" in store["text"]
    assert "GH token in package-lock.json is fine" in loaded


async def test_teach_this_bridge_does_not_leak() -> None:
    text = """# Learned

## 2026-09-14 — QdRepo/appt_sys_chep#9
**Scope:** only `QdRepo/appt_sys_chep`
Chep-only exception
"""
    assert "Chep-only" in filter_learned(text, "QdRepo", "appt_sys_chep")
    assert "Chep-only" not in filter_learned(text, "QdRepo", "appt_sys_e2openapi")


async def test_teach_write_failure_is_clean() -> None:
    comments: list[str] = []

    async def fail_append(*a, **k):
        raise RuntimeError("required status checks have not succeeded")

    with (
        patch("groundskeeper.review_runner.get_settings", return_value=fake_settings()),
        patch("groundskeeper.review_runner.resolve_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.learned_access_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.append_learned", fail_append),
        patch(
            "groundskeeper.review_runner.post_pr_comment",
            AsyncMock(side_effect=lambda *a, **k: comments.append(a[-1]) or 3),
        ),
        patch(
            "groundskeeper.review_runner.update_pr_comment",
            AsyncMock(side_effect=lambda *a, **k: comments.append(a[-1])),
        ),
    ):
        await teach_from_comment(1, "QdRepo", "appt_sys_chep", 9, "never fake REQUESTED")
    _assert_clean_fail(comments[-1], "could not save the note", "branch protection")


async def test_teach_defaults_to_all() -> None:
    saved = {}

    async def capture(token, lesson, **kw):
        saved.update({"lesson": lesson, **kw})

    with (
        patch("groundskeeper.review_runner.get_settings", return_value=fake_settings()),
        patch("groundskeeper.review_runner.resolve_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.learned_access_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.append_learned", capture),
        patch("groundskeeper.review_runner.post_pr_comment", AsyncMock(return_value=1)),
        patch("groundskeeper.review_runner.update_pr_comment", AsyncMock()),
    ):
        await teach_from_comment(1, "QdRepo", "x", 1, "don't warn about leftover sessions")
    assert saved["scope"] == "all"
    assert "sessions" in saved["lesson"]


async def test_help_and_override_fail_clean() -> None:
    posted: list[str] = []

    async def boom(*a, **k):
        raise RuntimeError("GitHub 403 writing: Resource not accessible by integration")

    with (
        patch("groundskeeper.review_runner.get_settings", return_value=fake_settings()),
        patch("groundskeeper.review_runner.resolve_token", AsyncMock(return_value="t")),
        patch(
            "groundskeeper.review_runner.post_pr_comment",
            AsyncMock(side_effect=lambda *a, **k: posted.append(a[-1]) or 1),
        ),
    ):
        await help_pr(1, "o", "r", 1)
    # first post is help; force failure on first post
    posted.clear()
    n = {"i": 0}

    async def fail_first(*a, **k):
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("GitHub 403 writing: Resource not accessible by integration")
        posted.append(a[-1])
        return 1

    with (
        patch("groundskeeper.review_runner.get_settings", return_value=fake_settings()),
        patch("groundskeeper.review_runner.resolve_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.post_pr_comment", fail_first),
    ):
        await help_pr(1, "o", "r", 1)
    _assert_clean_fail(posted[-1], "Could not post help", "cannot access")

    posted.clear()
    with (
        patch("groundskeeper.review_runner.resolve_token", AsyncMock(return_value="t")),
        patch("groundskeeper.review_runner.load_pr_bundle", AsyncMock(side_effect=boom)),
        patch(
            "groundskeeper.review_runner.post_pr_comment",
            AsyncMock(side_effect=lambda *a, **k: posted.append(a[-1]) or 1),
        ),
    ):
        await override_pr(1, "o", "r", 1, "mogiiee")
    _assert_clean_fail(posted[-1], "Could not override", "cannot access")


def test_webhook_routes() -> None:
    from fastapi.testclient import TestClient
    from groundskeeper.app import app

    settings = fake_settings()
    secret = settings.github_webhook_secret

    def signed(payload: dict, event: str):
        raw = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return raw, {
            "x-github-event": event,
            "x-hub-signature-256": sig,
            "content-type": "application/json",
        }

    def issue_comment(body: str, bot=False):
        return {
            "action": "created",
            "installation": {"id": 9},
            "repository": {"name": "appt_sys_x", "owner": {"login": "QdRepo"}},
            "issue": {"number": 23, "pull_request": {}},
            "comment": {
                "body": body,
                "user": {"login": "if-this-ships[bot]" if bot else "mogiiee", "type": "Bot" if bot else "User"},
            },
        }

    with (
        patch("groundskeeper.app.get_settings", return_value=settings),
        patch("groundskeeper.app.help_pr", AsyncMock()) as help_m,
        patch("groundskeeper.app.review_pr", AsyncMock()) as review_m,
        patch("groundskeeper.app.override_pr", AsyncMock()) as over_m,
        patch("groundskeeper.app.teach_from_comment", AsyncMock()) as teach_m,
        patch("groundskeeper.app.finish_pending_teach", AsyncMock()) as finish_m,
    ):
        client = TestClient(app)
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert health.json()["name"] == "if-this-ships"

        raw, headers = signed(issue_comment("@if-this-ships"), "issue_comment")
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["queued"] == "help"
        help_m.assert_awaited()

        raw, headers = signed(issue_comment("@if-this-ships review"), "issue_comment")
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["queued"] == "review"

        raw, headers = signed(issue_comment("@if-this-ships deep review"), "issue_comment")
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["queued"] == "deep"

        raw, headers = signed(issue_comment("@if-this-ships override"), "issue_comment")
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["queued"] == "override"
        over_m.assert_awaited()

        raw, headers = signed(
            issue_comment("@if-this-ships teach never fake REQUESTED"), "issue_comment"
        )
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["queued"] == "teach"

        raw, headers = signed(issue_comment("all bridges"), "issue_comment")
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["queued"] == "teach-scope"
        finish_m.assert_called()

        raw, headers = signed(issue_comment("@if-this-ships review", bot=True), "issue_comment")
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["skipped"] == "bot"

        raw, headers = signed({"zen": "x"}, "ping")
        r = client.post("/webhooks/github", content=raw, headers=headers)
        assert r.json()["ignored"] == "ping"

        bad = client.post(
            "/webhooks/github",
            content=b"{}",
            headers={"x-github-event": "ping", "x-hub-signature-256": "sha256=dead"},
        )
        assert bad.status_code == 400
        assert review_m.call_count >= 2


def live() -> None:
    url = (
        __import__("os").environ.get("IF_THIS_SHIPS_URL")
        or "https://if-b71048631b1d4d24a04d2d2601ef76f6.ecs.us-east-1.on.aws"
    )
    print(f"live health {url}/health")
    r = httpx.get(f"{url.rstrip('/')}/health", timeout=15)
    r.raise_for_status()
    data = r.json()
    assert data.get("ok") is True, data
    assert data.get("name") == "if-this-ships"
    print(f"  sha={data.get('sha')} githubApp={data.get('githubApp')} hasPat={data.get('hasPat')}")
    key = __import__("os").environ.get("ANTHROPIC_API_KEY") or ""
    if not key:
        print("  skip anthropic (no ANTHROPIC_API_KEY in this process)")
        return
    from groundskeeper.claude import complete_json
    from groundskeeper.env import get_settings

    get_settings.cache_clear()
    try:
        complete_json(
            model="claude-haiku-4-5",
            system="json only",
            user='Return {"ok": true}',
            max_tokens=32,
        )
        print("  anthropic ok")
    except Exception as e:
        body = fail_body("review", e)
        print(body)
        raise SystemExit("live anthropic failed cleanly; fix ANTHROPIC_API_KEY on the service") from e


def main() -> None:
    import logging

    logging.disable(logging.CRITICAL)
    print("stress")
    check("commands", test_commands)
    check("teach scope", test_teach_scope)
    check("core versions", test_core_versions)
    acheck("core snapshot skips missing files", test_core_snapshot_skips_missing_on_old_tag)
    check("lockfiles", test_lockfiles_and_truncation)
    check("review events", test_review_events)
    check("fail models", test_fail_models)
    acheck("pipeline versions in prompt", test_pipeline_versions_in_prompt)
    acheck("pipeline taught notes and deep", test_pipeline_taught_notes_and_deep)
    acheck("pipeline failure models", test_pipeline_failure_models)
    acheck("github 422 retry", test_submit_review_retries_without_inline_on_422)
    acheck("github hard fail is clean", test_submit_review_hard_fail_is_clean)
    acheck("review_pr posts clean fail", test_review_pr_posts_clean_fail)
    acheck("review_pr fail before progress", test_review_pr_fails_before_progress_still_comments)
    acheck("teach persists to notes repo", test_teach_persists_to_notes_repo)
    acheck("teach this-bridge isolation", test_teach_this_bridge_does_not_leak)
    acheck("teach write failure is clean", test_teach_write_failure_is_clean)
    acheck("teach defaults to all", test_teach_defaults_to_all)
    acheck("help and override fail clean", test_help_and_override_fail_clean)
    check("webhook routes", test_webhook_routes)
    if FAILURES:
        print("stress FAILED:", ", ".join(FAILURES))
        raise SystemExit(1)
    if "--live" in sys.argv:
        live()
    print("stress ok")


if __name__ == "__main__":
    main()
