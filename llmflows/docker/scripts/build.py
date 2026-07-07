"""Hatchling build hook: compiles the React frontend before packaging."""

import os
import shutil
import subprocess
from pathlib import Path
from sys import stderr

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


FRONTEND_DIR = "llmflows/ui/frontend"
STATIC_DIR = "llmflows/ui/static"


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        self._sync_docker_bundle()

        # If pre-built static files are already present (e.g. installed from git
        # with committed build output), skip the npm build entirely.
        if Path(STATIC_DIR, "index.html").exists():
            stderr.write(">>> llmflows React frontend already built, skipping npm build\n")
            return

        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "Node.js `npm` is required to build llmflows but was not found. "
                "Install Node.js from https://nodejs.org"
            )

        stderr.write(">>> Building llmflows React frontend\n")
        subprocess.run([npm, "install"], cwd=FRONTEND_DIR, check=True)
        stderr.write(">>> npm run build\n")
        subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, check=True)

    def _sync_docker_bundle(self):
        """Copy docker build inputs into the wheel for pip-only installs."""
        bundle = Path("llmflows/docker")
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "tools").mkdir(parents=True, exist_ok=True)
        (bundle / "scripts").mkdir(parents=True, exist_ok=True)
        for src, dest in (
            ("pyproject.toml", bundle / "pyproject.toml"),
            ("README.md", bundle / "README.md"),
            ("tools/package.json", bundle / "tools" / "package.json"),
            ("scripts/build.py", bundle / "scripts" / "build.py"),
        ):
            if Path(src).is_file():
                shutil.copy2(src, dest)
        stderr.write(">>> Synced docker build bundle into llmflows/docker/\n")
