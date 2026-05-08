"""Step executor routing -- dispatches to the right executor based on step_type."""

from .base import StepContext, StepExecutor, LaunchResult

_executor_cache: dict[str, StepExecutor] = {}


def get_executor(step_type: str, isolated: bool = False) -> StepExecutor:
    """Return a StepExecutor instance for the given step_type.

    When ``isolated`` is True, the returned executor wraps the inner
    executor in a DockerExecutor that runs the agent inside a container.
    """
    cache_key = f"{step_type}:isolated" if isolated else step_type
    if cache_key in _executor_cache:
        return _executor_cache[cache_key]

    if step_type == "code":
        from .code import CodeExecutor
        inner = CodeExecutor()
    else:
        from .pi import PiExecutor
        inner = PiExecutor()

    if isolated:
        from .docker import DockerExecutor
        executor = DockerExecutor(inner)
    else:
        executor = inner

    _executor_cache[cache_key] = executor
    return executor


__all__ = ["get_executor", "StepContext", "StepExecutor", "LaunchResult"]
