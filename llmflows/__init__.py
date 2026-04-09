"""llmflows -- agentic workflow orchestrator."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("llmflows")
except PackageNotFoundError:
    __version__ = "unknown"
