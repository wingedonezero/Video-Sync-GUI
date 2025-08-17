# Contributing

This document defines how we contribute, track changes, and keep everything in sync.
It serves as both a workflow guide and a set of standards for commits, patches, and
collaboration between humans and AI.

---

## 🔑 Always in Sync with `.chatpin`

- The `.chatpin` file is automatically updated on every commit to `main` by a GitHub Actions workflow.
- `.chatpin` contains exactly one commit SHA (the latest on `main`) followed by a trailing newline.
- This guarantees that ChatGPT, Git, and contributors are always referencing the same version.
- When generating patches or full-file replacements, always reference the SHA in `.chatpin`.
- If a new chat is started, `.chatpin` is the single source of truth for the repo state.

Rule: Never generate or apply a patch without syncing to `.chatpin`.

---

## 📜 Patch Standards

- All patches must use standard Git unified diff format (the same format used by GitKraken export and `git apply`).
- Each patch must be accompanied by:
  - Commit Title (short, imperative, semantic style, e.g., `fix: handle silent logging crash`).
  - Commit Message (multi-line if needed, explains why and what).
- Keep patches focused and atomic. Do not mix unrelated fixes and features.

Source of truth for "before" bytes
- Always base patches on the exact tree at the `.chatpin` SHA.
- Only include diffs for files that exist in that tree.
- If a file was already added in a prior commit, do not re-add it in later patches—regenerate the patch against the new `.chatpin` instead.
- This avoids "already exists in working directory" and hunk offset errors in GitKraken and `git apply`.
- When applying older patches locally, you may use:
  - `git apply --exclude=<path> ...` to skip hunks for files already present, or
  - regenerate the patch after updating `.chatpin` so it matches byte-for-byte.

---

## 🧹 Code Standards

- Python code must be formatted with Black (enforced).
- Follow PEP8 and maintain readability (comments, docstrings for complex logic).
- When cleaning/refactoring, do not change behavior unless fixing a clear bug.
- Modularize carefully — aim for maintainability, not unnecessary complexity.

---

## 📝 Logging & Output

- Logs should be compact but detailed enough for debugging.
- Avoid spam — summarize progress but include error context.
- Include:
  - Command executed (with `$` prefix).
  - Errors and stderr (trimmed to relevant lines).
  - Delay information (always applied, never subtracted).
  - Track order and merge options.
  - Final merge JSON/options so behavior is transparent.

---

## 🔄 Workflow

1. Sync: Ensure `.chatpin` is up to date.
2. Change: Make edits locally (or generate patch/full-file via ChatGPT based on `.chatpin`).
3. Test: Run locally before committing (do not break existing features).
4. Commit: Use semantic commit style + clear message.
5. Push: CI will update `.chatpin` automatically.

---

## ✅ Semantic Commit Types

- feat: New feature
- fix: Bug fix
- docs: Documentation only changes
- style: Code style/formatting only (no logic)
- refactor: Code change that neither fixes a bug nor adds a feature
- perf: Performance improvement
- test: Adding or updating tests
- chore: Tooling, CI, build, or maintenance
