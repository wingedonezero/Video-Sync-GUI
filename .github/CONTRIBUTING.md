# Contributing

This document describes how we contribute and keep Chat + Git in sync. It is a step‑by‑step guide.
For full design rationale and feature details, see the README in this same folder.

## Source of Truth: `.chatpin`

- `.chatpin` contains the exact commit SHA that patches and full‑file replacements must be based on.
- A GitHub Action in this repo already updates `.chatpin` on every push to `main`.
- Never generate or apply a patch without syncing to `.chatpin` first.

## Patch Standards

- Use **Git unified diffs** (compatible with `git apply` and GitKraken).
- ASCII + LF only (no BOM, no NBSP). If needed, normalize before applying.
- Patches must only include files that **exist at the `.chatpin` SHA**.
- Do **not** re‑add files already added in prior commits—regenerate against the latest `.chatpin` instead.
- Keep patches atomic and focused.

### Troubleshooting
```bash
# strip BOM, NBSP, CRLF if needed
perl -CSDA -pe 's/\x{FEFF}//g; s/\x{00A0}/ /g; s/\r//g' file.patch > /tmp/clean.patch
git apply --check /tmp/clean.patch && git apply /tmp/clean.patch
```

## Commit Messages

- **Title**: imperative, semantic (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `logs:`, `ui:`), ≤72 chars.
- **Body**: explain **why** and **what**; reference behavior/README updates.
- Update the README in the same commit when features change (add/remove/behavior shift).

## Code Standards

- Python 3.10+, formatted with **Black** (see `pyproject.toml`).
- Imports sorted with **isort** (Black profile).
- Editor/CI line endings: **LF** only; UTF‑8; final newline; trim trailing whitespace.
- Avoid breaking behavior when refactoring; prefer small, reviewable changes.

## Development Workflow

1. Sync to `.chatpin` (pull, ensure you’re on the pinned tree).
2. Make changes locally (or apply a patch built against `.chatpin`).
3. `make format` (Black + isort) or run pre‑commit.
4. Test locally.
5. Commit with semantic title and clear message.
6. Push; CI updates `.chatpin` automatically.
