"""Built-in reporters for function, coverage, and crash output."""

from futagassist.reporters.html_reporter import HtmlReporter
from futagassist.reporters.json_reporter import JsonReporter
from futagassist.reporters.sarif_reporter import SarifReporter


def register_builtin_reporters(registry) -> None:
    """Register built-in reporters on the given registry."""
    registry.register_reporter("json", JsonReporter)
    registry.register_reporter("sarif", SarifReporter)
    registry.register_reporter("html", HtmlReporter)


__all__ = [
    "HtmlReporter",
    "JsonReporter",
    "SarifReporter",
    "register_builtin_reporters",
]
