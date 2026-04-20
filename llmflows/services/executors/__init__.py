"""Step executor routing -- dispatches to the right executor based on step_type."""

from .base import StepContext, StepExecutor, LaunchResult

_executor_cache: dict[str, StepExecutor] = {}


def get_executor(step_type: str) -> StepExecutor:
    """Return a StepExecutor instance for the given step_type."""
    if step_type in _executor_cache:
        return _executor_cache[step_type]

    if step_type == "code":
        from .code import CodeExecutor
        executor = CodeExecutor()
    else:
        from .pi import PiExecutor
        executor = PiExecutor()

    _executor_cache[step_type] = executor
    return executor


__all__ = ["get_executor", "StepContext", "StepExecutor", "LaunchResult"]
