"""Base executor abstraction for step execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StepContext:
    """All data an executor needs to run a step."""

    run_id: str
    step_name: str
    step_position: int
    step_content: str
    flow_name: str
    agent: str
    model: str
    step_type: str
    working_path: Path
    space_dir: Path
    artifacts_dir: Path
    gate_failures: Optional[list[dict]] = None
    resume_prompt: str = ""
    attempt: int = 1
    user_responses: Optional[list[dict]] = None
    space_variables: Optional[dict] = None
    skills: Optional[list[dict]] = None
    extra_env: Optional[dict[str, str]] = None
    log_path: str = ""
    prompt_content: str = ""

    @property
    def step_dir_name(self) -> str:
        return f"{self.step_position:02d}-{self.step_name.replace(' ', '-')}"


@dataclass
class LaunchResult:
    """Result of launching a step."""

    success: bool
    prompt_content: str = ""
    log_path: str = ""
    output: str = ""
    is_sync: bool = False


class StepExecutor(ABC):
    """Base class for step executors.

    Executors handle different step_type values: code, agent/hitl.
    Async executors (code) launch a subprocess and return; the daemon polls
    is_running(). Sync executors complete within launch() and set
    is_sync=True on the result.
    """

    @abstractmethod
    def launch(self, ctx: StepContext) -> LaunchResult:
        """Start executing the step."""
        ...

    @abstractmethod
    def is_running(self, ctx: StepContext) -> bool:
        """Check if the step is still executing (async executors only)."""
        ...

    @abstractmethod
    def get_output(self, ctx: StepContext) -> Optional[str]:
        """Retrieve the output after completion."""
        ...
