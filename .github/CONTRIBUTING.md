# Contributing

This document defines how we contribute, track changes, and keep everything in sync.
It serves as both a workflow guide and a set of standards for commits, patches, and
collaboration between humans and AI.

---

## 🔑 Always in Sync with `.chatpin`

- The `.chatpin` file is **automatically updated** on every commit to `main` by a GitHub Actions workflow.
- `.chatpin` contains exactly one commit SHA (the latest on `main`) followed by a trailing newline.
- This guarantees that ChatGPT, Git, and contributors are always referencing the same version.
- When generating patches, we always reference the SHA in `.chatpin`.
- If a new chat is started, `.chatpin` is the single source of truth for the repo state.

📌 **Rule:** *Never* generate or apply a patch without syncing to `.chatpin`.

---

## 📜 Patch Standards

- Patches must use **standard Git unified diff** format (compatible with GitKraken *Apply Patch* and `git apply`):
  - starts with `--- a/path` and `+++ b/path`, followed by `@@ … @@` hunk headers,
  - `-` removed lines, `+` added lines, and space-prefixed context.
- Each patch must include:
  - **Commit Title** (short, imperative, semantic style, e.g., `fix: handle silent logging crash`).
  - **Commit Message** (multi-line if needed, explains *why* and *what*).
- Keep patches focused and atomic. Don’t mix unrelated fixes and features.

---

## 🧹 Code Standards

- Python code must be formatted with **Black** (enforced).
- Follow PEP8 and maintain readability (comments, docstrings for complex logic).
- When cleaning/refactoring, **don’t change behavior unless fixing a clear bug**.
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

1. **Sync**: Ensure `.chatpin` is up to date.
2. **Change**: Make edits locally (or generate patch via ChatGPT).
3. **Test**: Run locally before committing (don’t break existing features).
4. **Commit**: Use semantic commit style + clear message.
5. **Push**: CI will update `.chatpin` automatically.

---

## ✅ Semantic Commit Types

- **feat:** New feature
- **fix:** Bug fix
- **docs:** Documentation only changes
- **style:** Code style/formatting only (no logic)
- **refactor:** Code change that neither fixes a bug nor adds a feature
- **perf:** Performance improvement
- **test:** Adding or updating tests
- **chore:** Tooling, CI, build, or maintenance
