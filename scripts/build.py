"""Hatchling build hook: compiles the React frontend before packaging."""

import shutil
import subprocess
from sys import stderr

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


FRONTEND_DIR = "llmflows/ui/frontend"


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
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
