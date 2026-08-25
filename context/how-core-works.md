# How core works

Core repo: `QdRepo/appt_bridge_core` (version from the PR `package.json` tag, e.g. `#v1.0.59`). Fetched from GitHub — never from `node_modules`.

## Lifecycle (core owns this)

1. Format request → `AppointmentDetails`
2. Credentials (if auth required)
3. `init` → `login` (auth lock if `useAuthLock`)
4. `verifyAppointment` before create/change/cancel (most paths)
5. Route from verify → cancel / track / early return / change / create
6. Always `logout()` then `close()`

## VerifyResult matters

Wrong `exists`, `isRequestChanged`, or `rescheduleAllowed` changes which process runs. Call that out.

## Results

- Results must include `appointment`.
- Outbound keeps original request as `appt_req`.
- Login failure stops before verify/create.

## Browser

Prod = Hyperbrowser. `close()` must stop the session.
