---
name: release
description: Release llmflows: bump version, commit, tag, and push. Use when the user wants to release, publish, ship, bump version, create a tag, or commit and push changes to the llmflows project.
---

# Release llmflows

The React frontend is built automatically by `hatch_build.py` during packaging — no manual build step needed.

## Steps

### 1. Bump the version

Version is defined in one place: `pyproject.toml` under `[project] version`. Follow semver:
- **patch** `0.x.Y` — bug fixes
- **minor** `0.X.0` — new features, backwards compatible
- **major** `X.0.0` — breaking changes

### 2. Commit

```bash
git add -u
git commit -m "release: v<version>"
```

### 3. Tag and push

```bash
git tag v<version>
git push origin main
git push origin v<version>
```

## How the frontend gets built

- `hatch_build.py` runs `npm install` + `npm run build` automatically when the package is built (via `hatch build` or `pip install` from source)
- The compiled output (`llmflows/ui/static/`) is **not committed to git** — it's generated fresh each build
- End users installing from git (`pip install git+https://...`) need Node.js available at install time

## Notes

- Tag format is always `v<version>` (e.g. `v0.4.0`), matching `pyproject.toml`
- No need to build the frontend manually before committing
