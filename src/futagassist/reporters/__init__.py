"""Built-in reporters for function, coverage, and crash output."""

from futagassist.reporters.json_reporter import JsonReporter


def register_builtin_reporters(registry) -> None:
    """Register built-in reporters on the given registry."""
    registry.register_reporter("json", JsonReporter)


__all__ = [
    "JsonReporter",
    "register_builtin_reporters",
]
