"""Step executor routing -- dispatches to the right executor based on step_type."""

from .base import StepContext, StepExecutor, LaunchResult

_executor: StepExecutor | None = None


def get_executor(step_type: str) -> StepExecutor:
    """Return a StepExecutor instance for the given step_type.

    All step types use PiExecutor — coding CLI agents are not supported.
    """
    global _executor
    if _executor is None:
        from .pi import PiExecutor
        _executor = PiExecutor()
    return _executor


__all__ = ["get_executor", "StepContext", "StepExecutor", "LaunchResult"]
