"""Hatchling build hook: compiles the React frontend before packaging."""

import os
import shutil
import subprocess
from pathlib import Path
from sys import stderr

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


FRONTEND_DIR = "llmflows/ui/frontend"
STATIC_DIR = "llmflows/ui/static"
DOCKER_BUNDLE = Path("llmflows/docker")

# Copied into the wheel at build time for pip-only Docker image builds.
DOCKER_BUNDLE_FILES = (
    ("Dockerfile", DOCKER_BUNDLE / "Dockerfile"),
    ("pyproject.toml", DOCKER_BUNDLE / "pyproject.toml"),
    ("uv.lock", DOCKER_BUNDLE / "uv.lock"),
    ("README.md", DOCKER_BUNDLE / "README.md"),
    ("tools/package.json", DOCKER_BUNDLE / "tools" / "package.json"),
    ("scripts/build.py", DOCKER_BUNDLE / "scripts" / "build.py"),
)


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
        DOCKER_BUNDLE.mkdir(parents=True, exist_ok=True)
        (DOCKER_BUNDLE / "tools").mkdir(parents=True, exist_ok=True)
        (DOCKER_BUNDLE / "scripts").mkdir(parents=True, exist_ok=True)
        for src, dest in DOCKER_BUNDLE_FILES:
            src_path = Path(src)
            if src_path.is_file():
                shutil.copy2(src_path, dest)
        stderr.write(">>> Synced docker build bundle into llmflows/docker/\n")
