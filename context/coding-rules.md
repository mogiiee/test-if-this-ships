# Coding rules

## Style

YAGNI. Fewest files. No unrequested abstractions. No leftover self-checks in production helpers. Mark shortcuts with `ponytail:` (ceiling + upgrade path).

## Which file holds what

| Concern | File |
|---|---|
| Auth (captcha/MFA) | `authenticateHelper.ts` |
| Verify | `verificationHelper.ts` |
| Create | `newAppointmentHelper.ts` |
| Change | `changeAppointmentHelper.ts` |
| Cancel | `cancelAppointmentHelper.ts` |
| Shared by 2+ of create/change/cancel | `baseAppointmentHelper.ts` |
| Logout | `src/bridges/<name>Bridge.ts` → `logout()` |

Logout must be real UI logout.

## Payload

`details.*` / `details.payload.*` only. Never `originalRequest` in helpers.

## Errors

- No `try/catch` unless explicitly required. UI failures go through core `step()`, not a local catch.
- Terminal UI/parse failures: `AuditError`.
- Business outcomes: `errorResponse` / `successResponse` + `ErrorType`.
- `REQ_OPT_NOT_FOUND`: return all options; key = payload field name.

## `step()` (mandatory on every UI stage)

Every UI stage in a helper runs inside `step` from `appt-bridge-core`. Call `this.step(label, fn)` on `BaseAppointmentHelper`. That passes `page`, `screenShotList`, `details.tenant` as folderName, and `details.slot.locationStopId` as stopId.

- Each stage is its own call: open the page, fill the form, read the result, search slots, return to the previous page, select, submit. One wrap around `process()` is not enough.
- Do not nest `step()` inside `step()`.
- `step` screenshots and rethrows `AuditError` type `uiIssues`. That is the only catch.
- Payload `AuditError` (missing required data) stays **outside** `step` so the type stays `payloadIssue`.
- Business `errorResponse` / `successResponse` stay returns. `step` does not turn those into throws.

## Hyperbrowser

Prod runs on Hyperbrowser. Write waits for that. Screenshot fragile steps. No local-Chrome-only paths.

## After search / API UI

Settle → network idle → then read rows/options.

## Outbound response

Correct `status` + `appt_req`. EXCEPTION needs `exc_type`. Wrong shape → dropped, not retried.
