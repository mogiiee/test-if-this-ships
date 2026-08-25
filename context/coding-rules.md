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

- No `try/catch` unless explicitly required.
- Terminal UI/parse failures: `AuditError`.
- Business outcomes: `errorResponse` / `successResponse` + `ErrorType`.
- `REQ_OPT_NOT_FOUND`: return all options; key = payload field name.

## Hyperbrowser

Prod runs on Hyperbrowser. Write waits for that. Screenshot fragile steps. No local-Chrome-only paths.

## After search / API UI

Settle → network idle → then read rows/options.

## Outbound response

Correct `status` + `appt_req`. EXCEPTION needs `exc_type`. Wrong shape → dropped, not retried.
