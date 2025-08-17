Move to modular approach split project into modules so its easier to work on and know whats being broke or fixed

use https://github.com/psf/black for coder formatting so we have a specic code format and smaller unified diff patches.
So explicit black formatiing from now on.

update changelog.md with every commit

Patch scope

Updates should include:
Unified diff patch
Commit title
Commit messages

Conventional commits:

feat: …, fix: …, refactor: …, chore: …, docs: …, logs: …, ui: …

Title ≤ 72 chars; body says what & why, not “how”. Include risk/rollback note.


Review gates (PR checklist)

✅ Covers: purpose, scope, risks.

✅ Touches allowed areas only (e.g., not run_command or UI unless stated).

✅ Logs: human-readable, not spammy; machine JSON captured, not streamed.

✅ Tests run locally (Analyze-only + Normal Merge on fixtures).

✅ Revert path: single-commit revert possible.

Updates and patches should be done from the current version of the main branch and work to fix or add from there.


Source-of-truth + diff rules

.chatpin = baseline commit

Put a file at repo root named .chatpin containing exactly the commit SHA I should treat as “before”.

Example: 5252151820330c3aa55253f943910b7405456ccc

When you push new work, you can either leave .chatpin alone (so I diff new → .chatpin) or update .chatpin to advance the baseline.

Diff scope (relevance filter)

By default I’ll consider all tracked files but only include files relevant to the change:

Python: *.py

Config: *.json, pyproject.toml, .pre-commit-config.yaml

Docs: README.md, CONTRIBUTING.md, CHANGELOG.md

CI scripts / entry points if needed for the change

I won’t touch unrelated assets (images, large samples) unless you ask.

Patch packaging

I’ll deliver one unified diff touching multiple files when appropriate, plus:

a short commit title

a commit message body (purpose, what/why, rollback note)

If you prefer mailbox (git am) patches later, I can switch.

Branching: feat/..., fix/..., refactor/..., logs/..., ui/...

Protected areas: don’t modify run_command or DPG pump in mixed PRs; dedicate a PR and label risk:high if needed.

Feature flags: new behavior is behind a flag, default off.

Commit style: Conventional Commits, ≤72-char title; body explains what/why and includes rollback note.

PR checklist: purpose, scope, risks & rollback, test notes (Analyze-only + Dry-run merge on fixtures).

Logging rules: deterministic points only; big JSON captured silently; progress throttled; error tails limited.

Reverts: each PR must be revertible by a single git revert <sha>.
