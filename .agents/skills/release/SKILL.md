---
name: release
description: Release llmflows: build React frontend, bump version, commit, tag, and push. Use when the user wants to release, publish, ship, bump version, create a tag, or commit and push changes to the llmflows project.
---

# Release llmflows

## Steps

### 1. Build the React frontend

```bash
cd llmflows/ui/frontend
npm run build
cd ../../..
```

This compiles the UI into `llmflows/ui/static/` — required for users who install from git.

### 2. Bump the version

Version is defined in one place: `pyproject.toml` under `[project] version` (`__init__.py` reads it automatically at runtime). Follow semver:
- **patch** `0.x.Y` — bug fixes
- **minor** `0.X.0` — new features, backwards compatible
- **major** `X.0.0` — breaking changes

Edit `pyproject.toml` and update the `version` field.

### 3. Commit

Stage everything and commit:

```bash
git add llmflows/ui/static/ pyproject.toml
git add -u   # any other modified tracked files
git commit -m "release: v<version>"
```

### 4. Tag and push

```bash
git tag v<version>
git push origin main
git push origin v<version>
```

## Rules

- **Never push frontend source changes without building first.** The pre-push hook enforces this — if it fires, run step 1 and amend the commit.
- Tag format is always `v<version>` (e.g. `v0.3.3`), matching the version in `pyproject.toml`.
- If only Python files changed (no frontend edits), skip step 1.
