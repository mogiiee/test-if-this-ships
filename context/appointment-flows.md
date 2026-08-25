# Appointment flows

Name the flow when a PR touches it:

- **auth** — login, captcha, OTP/2FA, credential lock
- **verify** — search/track; routes to create vs change/cancel
- **create** — new appointment, slot window, post-submit check
- **change** — modify existing
- **cancel** — unschedule
- **logout** — real UI sign-out (always required)
- **response** — result / ErrorType / post-processor JSON
- **hyperbrowser** — waits, selectors, settle, screenshots
- **payload** — `details` / `details.payload` reads

If the PR redirects process behavior, say so even without claiming a bug.
