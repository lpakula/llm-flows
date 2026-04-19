---
name: release
description: Release llmflows: bump version, commit, tag, and push. Use when the user wants to release, publish, ship, bump version, create a tag, or commit and push changes to the llmflows project.
---

# Release llmflows

The React frontend must be built and committed before releasing, so end users installing via `pip install git+https://...` don't need Node.js.

## Steps

### 1. Build the frontend

```bash
cd llmflows/ui/frontend && npm run build
```

This outputs compiled files to `llmflows/ui/static/` which must be committed.

### 2. Bump the version

Version is defined in one place: `pyproject.toml` under `[project] version`. Follow semver:
- **patch** `0.x.Y` — bug fixes
- **minor** `0.X.0` — new features, backwards compatible
- **major** `X.0.0` — breaking changes

### 3. Commit

```bash
git add -u
git add llmflows/ui/static/
git commit -m "release: v<version>"
```

### 4. Tag and push

```bash
git tag v<version>
git push origin main
git push origin v<version>
```

## Notes

- Tag format is always `v<version>` (e.g. `v0.4.0`), matching `pyproject.toml`
- The build hook in `scripts/build.py` skips `npm build` if `static/index.html` already exists, so the committed static files are used as-is on install
- If there are no frontend changes in the release, the `npm run build` step can be skipped (existing static files are still committed and correct)
