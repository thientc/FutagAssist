"""LLM-assisted analysis: suggest additional usage contexts from function list and optional code."""

from __future__ import annotations

import re
from pathlib import Path

from futagassist.core.schema import FunctionInfo, UsageContext


USAGE_CONTEXT_PROMPT = """You are helping generate fuzz targets. Given a list of function names and existing usage contexts (ordered call sequences), suggest ADDITIONAL usage contexts: ordered sequences of function calls that would be useful for fuzzing (e.g. init then use then cleanup, parse then process).

Rules:
- Output one usage context per line in this exact format: name: func1, func2, func3
- "name" is a short label (e.g. init_use_cleanup). "func1, func2, func3" are function names from the list below, in call order.
- Use ONLY function names from the provided list. Do not invent names.
- Do not duplicate the existing usage contexts listed below.
- If you have no additional suggestions, output nothing (empty response).

Available functions (name / signature):
{function_list}

Existing usage contexts (do not duplicate):
{existing_contexts}
{code_snippet_block}

Suggest additional usage contexts, one per line: name: func1, func2, func3"""


def suggest_usage_contexts(
    llm: object,
    functions: list[FunctionInfo],
    usage_contexts: list[UsageContext],
    repo_path: Path | None = None,
) -> list[UsageContext]:
    """
    Ask the LLM to suggest additional usage contexts (ordered function-call sequences).

    Given the list of functions and existing usage_contexts, the LLM suggests extra
    ordered call sequences useful for fuzzing. On LLM error or parse failure, returns [].
    """
    if not functions:
        return []
    if not getattr(llm, "complete", None) or not callable(getattr(llm, "complete")):
        return []

    function_names = {f.name for f in functions}
    function_list = "\n".join(f"- {f.name}: {f.signature}" for f in functions[:200])
    existing = "\n".join(
        f"- {u.name}: {', '.join(u.calls)}" for u in usage_contexts[:50]
    ) or "(none)"
    code_snippet_block = ""
    if functions and any(f.context for f in functions):
        snippets = [f"{f.name}:\n{f.context[:500]}" for f in functions[:10] if f.context][:3]
        if snippets:
            code_snippet_block = "\n\nRelevant code snippets:\n" + "\n---\n".join(snippets)

    prompt = USAGE_CONTEXT_PROMPT.format(
        function_list=function_list,
        existing_contexts=existing,
        code_snippet_block=code_snippet_block,
    )

    try:
        response = llm.complete(prompt).strip()
    except Exception as e:
        _log_warning("LLM usage context suggestion failed: %s", e)
        return []

    return _parse_usage_context_response(response, function_names)


def _parse_usage_context_response(
    response: str,
    valid_names: set[str],
) -> list[UsageContext]:
    """Parse LLM response into list of UsageContext. Invalid lines are skipped."""
    import logging
    log = logging.getLogger("futagassist.analysis.llm_analyze")
    result: list[UsageContext] = []
    for line in response.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([^:]+):\s*(.+)$", line)
        if not match:
            continue
        name = match.group(1).strip()
        calls_str = match.group(2).strip()
        calls = [c.strip() for c in calls_str.split(",") if c.strip()]
        if not calls:
            continue
        if not all(c in valid_names for c in calls):
            log.debug("Skipping line (unknown function name): %s", line[:80])
            continue
        result.append(UsageContext(name=name or "unnamed", calls=calls))
    return result


def _log_warning(msg: str, *args: object) -> None:
    import logging
    logging.getLogger("futagassist.analysis.llm_analyze").warning(msg, *args)
