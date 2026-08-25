# Always flag these

If the PR introduces or leaves any of these, always post a finding. These are not style nits.

1. **Stub / missing logout** — empty, TODO, or not real site UI logout. Core always calls `logout()` then `close()`.
2. **`try/catch` in bridge helpers** — breaks `ErrorClassifier` (it matches on `error.message`). Let errors propagate unless the developer explicitly required a catch.
3. **Reading `originalRequest` in helpers** — use `details.*` / `details.payload.*` only.
4. **`throw new Error(...)`** for helper failures — use `AuditError(...)` instead.
5. **Invented defaults / guessed UI / unapproved status mappings**.
6. **Fragile Hyperbrowser selectors** — especially `locator('a, b, c').first()`. Prefer `.or()`, one selector, role/placeholder. `networkidle` is not “UI ready”.
7. **Reading UI right after search/API** — settle, then network idle, then read.
8. **Wrong `VerifyResult` fields** — bad `exists` / `isRequestChanged` / `rescheduleAllowed` sends the job down the wrong create/change path.
9. **`REQ_OPT_NOT_FOUND` wrong key** — `invalid_field` and metadata key must match the Payload field name (e.g. `reasonCode`, not `reason`).
10. **Broken response contract** — wrong/missing fields; post-processor drops bad messages (no retry).
11. **Fake success** — REQUESTED/CONFIRMED while the UI still shows unscheduled. Use retriable `AuditError` when the next run should retry.
12. **Business EXCEPTION as a bare throw** — use `errorResponse` / `successResponse` + `ErrorType`.
13. **OTP/2FA without auth lock**.
14. **Self-check / assert demos left in production helpers**.
15. **Rebuilding core-owned pieces** (SQS handler, browser launch) instead of using `appt-bridge-core`.
