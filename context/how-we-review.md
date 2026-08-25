# How we review

- Point developers in the right direction. They are smarter than the model. Do not lecture or rewrite the PR.
- Silence is valid. No rule breaks and no flow risk → zero findings, one-line clean summary.
- Not every line needs a comment. Not every finding needs a patch.
- PR size does not matter.
- When a change alters auth, verify routing, create/change/cancel, logout, or response shape, say which flow changes — even if you are not claiming a bug.
- Suggest patches only when a small concrete fix clearly helps.
- Harmful findings must state: (1) what the change is trying to do, (2) if this ships → which process does what wrong, (3) why, (4) how to fix.
