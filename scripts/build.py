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
