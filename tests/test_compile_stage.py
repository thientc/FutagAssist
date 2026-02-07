"""Tests for CompileStage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from futagassist.core.config import AppConfig, ConfigManager
from futagassist.core.registry import ComponentRegistry
from futagassist.core.schema import GeneratedHarness, PipelineContext, StageResult

from _helpers import make_config_manager, make_sample_harness
from futagassist.stages.compile_stage import (
    DEFAULT_COMPILE_FLAGS,
    DEFAULT_COMPILE_TIMEOUT,
    MAX_BACKOFF_SECONDS,
    MAX_COMPILER_ERROR_LINES,
    MAX_ERROR_OUTPUT_CHARS,
    MAX_SOURCE_CODE_CHARS,
    CompileStage,
    _binary_name,
    _parse_compiler_errors,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Aliases for backward compatibility with existing test code.
_make_harness = make_sample_harness
_make_config_manager = make_config_manager


def _make_context(
    tmp_path: Path,
    harnesses: list[GeneratedHarness] | None = None,
    fuzz_prefix: Path | None = None,
    extra_config: dict | None = None,
) -> PipelineContext:
    registry = ComponentRegistry()
    from futagassist.stages import register_builtin_stages
    register_builtin_stages(registry)
    config_mgr = _make_config_manager(tmp_path)
    config = {
        "registry": registry,
        "config_manager": config_mgr,
        **(extra_config or {}),
    }
    return PipelineContext(
        repo_path=tmp_path,
        generated_harnesses=harnesses or [],
        fuzz_install_prefix=fuzz_prefix,
        config=config,
    )


# ---------------------------------------------------------------------------
# Unit tests: _parse_compiler_errors
# ---------------------------------------------------------------------------


class TestParseCompilerErrors:
    def test_extracts_error_lines(self) -> None:
        stderr = (
            "harness.cpp:5:10: error: use of undeclared identifier 'foo'\n"
            "    foo();\n"
            "    ^~~~\n"
            "1 error generated.\n"
        )
        errors = _parse_compiler_errors(stderr)
        assert len(errors) == 1
        assert "undeclared identifier" in errors[0]

    def test_extracts_fatal_errors(self) -> None:
        stderr = "harness.cpp:1:10: fatal error: 'nonexistent.h' file not found\n"
        errors = _parse_compiler_errors(stderr)
        assert len(errors) == 1
        assert "file not found" in errors[0]

    def test_limits_to_10(self) -> None:
        lines = [f"harness.cpp:{i}: error: err{i}\n" for i in range(20)]
        errors = _parse_compiler_errors("".join(lines))
        assert len(errors) == 10

    def test_empty_input(self) -> None:
        assert _parse_compiler_errors("") == []

    def test_no_errors(self) -> None:
        stderr = "harness.cpp:5:10: warning: unused variable\n"
        assert _parse_compiler_errors(stderr) == []


# ---------------------------------------------------------------------------
# Unit tests: _binary_name
# ---------------------------------------------------------------------------


class TestBinaryName:
    def test_simple_name(self) -> None:
        h = _make_harness("my_func")
        assert _binary_name(h) == "fuzz_my_func"

    def test_special_chars_sanitized(self) -> None:
        h = _make_harness("ns::func<int>")
        name = _binary_name(h)
        assert name == "fuzz_ns__func_int_"
        assert "/" not in name
        assert "<" not in name


# ---------------------------------------------------------------------------
# CompileStage: input validation
# ---------------------------------------------------------------------------


class TestCompileStageValidation:
    def test_no_harnesses(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, harnesses=[])
        stage = CompileStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "No generated harnesses" in result.message

    def test_no_valid_harnesses(self, tmp_path: Path) -> None:
        ctx = _make_context(tmp_path, harnesses=[_make_harness("bad", valid=False)])
        stage = CompileStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "0 valid" in result.message

    def test_harness_without_source(self, tmp_path: Path) -> None:
        h = GeneratedHarness(function_name="empty", source_code="", is_valid=True)
        ctx = _make_context(tmp_path, harnesses=[h])
        stage = CompileStage()
        result = stage.execute(ctx)
        assert result.success is False

    def test_no_registry(self, tmp_path: Path) -> None:
        ctx = PipelineContext(
            repo_path=tmp_path,
            generated_harnesses=[_make_harness()],
            config={},
        )
        stage = CompileStage()
        result = stage.execute(ctx)
        assert result.success is False
        assert "registry" in result.message.lower()


# ---------------------------------------------------------------------------
# CompileStage: compilation (mocked subprocess)
# ---------------------------------------------------------------------------


class TestCompileStageExecution:
    def test_compile_success(self, tmp_path: Path) -> None:
        """When compiler exits 0 for all harnesses, stage succeeds."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("foo"), _make_harness("bar")],
        )
        stage = CompileStage()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            result = stage.execute(ctx)

        assert result.success is True
        assert result.data["compiled_count"] == 2
        assert result.data["failed_count"] == 0
        assert "binaries_dir" in result.data

    def test_compile_failure_all(self, tmp_path: Path) -> None:
        """When all harnesses fail to compile, stage fails."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("foo")],
            extra_config={"compile_use_llm": False},
        )
        stage = CompileStage()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error: undeclared", stdout="")
            result = stage.execute(ctx)

        assert result.success is False
        assert result.data["compiled_count"] == 0
        assert result.data["failed_count"] == 1
        assert "All" in result.message

    def test_compile_partial_success(self, tmp_path: Path) -> None:
        """When some harnesses compile and others fail, stage succeeds with counts."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("good"), _make_harness("bad")],
            extra_config={"compile_use_llm": False},
        )
        stage = CompileStage()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call succeeds, second fails
            if call_count == 1:
                return MagicMock(returncode=0, stderr="", stdout="")
            return MagicMock(returncode=1, stderr="error: bad", stdout="")

        with patch("subprocess.run", side_effect=side_effect):
            result = stage.execute(ctx)

        assert result.success is True
        assert result.data["compiled_count"] == 1
        assert result.data["failed_count"] == 1
        assert "1/2" in result.message

    def test_compile_writes_source_files(self, tmp_path: Path) -> None:
        """Stage writes harness source to binaries_dir before compiling."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("test_func")],
            extra_config={"compile_output": str(tmp_path / "out")},
        )
        stage = CompileStage()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            result = stage.execute(ctx)

        assert result.success is True
        source = tmp_path / "out" / "fuzz_test_func.cpp"
        assert source.exists()
        assert "LLVMFuzzerTestOneInput" in source.read_text()

    def test_compile_custom_compiler(self, tmp_path: Path) -> None:
        """Custom compiler is passed to subprocess."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("f")],
            extra_config={"compile_compiler": "g++", "compile_use_llm": False},
        )
        stage = CompileStage()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            result = stage.execute(ctx)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "g++"

    def test_compile_compiler_not_found(self, tmp_path: Path) -> None:
        """When compiler binary is not found, compilation fails gracefully."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("f")],
            extra_config={
                "compile_compiler": "/nonexistent/clang++",
                "compile_use_llm": False,
            },
        )
        stage = CompileStage()
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            result = stage.execute(ctx)

        assert result.success is False
        assert result.data["failed_count"] == 1

    def test_compile_timeout(self, tmp_path: Path) -> None:
        """When compiler times out, compilation fails gracefully."""
        import subprocess as sp

        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("f")],
            extra_config={"compile_use_llm": False, "compile_timeout": 5},
        )
        stage = CompileStage()
        with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="clang++", timeout=5)):
            result = stage.execute(ctx)

        assert result.success is False
        assert result.data["failed_count"] == 1


# ---------------------------------------------------------------------------
# CompileStage: fuzz install prefix linking
# ---------------------------------------------------------------------------


class TestCompileStagePrefix:
    def test_link_flags_from_prefix(self, tmp_path: Path) -> None:
        """When fuzz_install_prefix has lib/ and include/, link flags are added."""
        prefix = tmp_path / "install-fuzz"
        (prefix / "lib").mkdir(parents=True)
        (prefix / "include").mkdir(parents=True)

        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("f")],
            fuzz_prefix=prefix,
            extra_config={"compile_use_llm": False},
        )
        stage = CompileStage()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            result = stage.execute(ctx)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        cmd_str = " ".join(str(a) for a in call_args)
        assert f"-L{prefix / 'lib'}" in cmd_str
        assert f"-I{prefix / 'include'}" in cmd_str
        assert "-rpath" in cmd_str

    def test_no_prefix_no_link_flags(self, tmp_path: Path) -> None:
        """Without fuzz_install_prefix, no -L/-I flags are added."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("f")],
            extra_config={"compile_use_llm": False},
        )
        stage = CompileStage()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            result = stage.execute(ctx)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        cmd_str = " ".join(str(a) for a in call_args)
        assert "-L" not in cmd_str
        assert "-Wl,-rpath" not in cmd_str


# ---------------------------------------------------------------------------
# CompileStage: LLM-assisted fixing
# ---------------------------------------------------------------------------


class TestCompileStageLLM:
    def test_llm_fix_retries_and_succeeds(self, tmp_path: Path) -> None:
        """When first compile fails and LLM fixes the source, retry succeeds."""

        class MockLLM:
            name = "mock"

            def complete(self, prompt: str, **kwargs) -> str:
                return (
                    '#include <stdint.h>\n'
                    'extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {\n'
                    '    return 0;\n'
                    '}\n'
                )

            def check_health(self) -> bool:
                return True

        registry = ComponentRegistry()
        from futagassist.stages import register_builtin_stages
        register_builtin_stages(registry)
        registry.register_llm("mock", type(MockLLM()))
        config_mgr = _make_config_manager(tmp_path)
        # Override llm_provider to use mock
        config_mgr._config.llm_provider = "mock"

        ctx = PipelineContext(
            repo_path=tmp_path,
            generated_harnesses=[_make_harness("f")],
            config={
                "registry": registry,
                "config_manager": config_mgr,
                "compile_max_retries": 1,
            },
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(returncode=1, stderr="error: missing header", stdout="")
            return MagicMock(returncode=0, stderr="", stdout="")

        stage = CompileStage()
        with patch("subprocess.run", side_effect=side_effect), \
             patch("time.sleep"):
            result = stage.execute(ctx)

        assert result.success is True
        assert call_count == 2  # first fail + retry success

    def test_llm_returns_unfixable(self, tmp_path: Path) -> None:
        """When LLM returns UNFIXABLE, no retry is attempted."""
        stage = CompileStage()
        result = stage._ask_llm_for_fix(
            llm=MagicMock(complete=MagicMock(return_value="UNFIXABLE")),
            compile_cmd="clang++ foo.cpp",
            source_file="foo.cpp",
            error_output="error: undeclared",
            source_code="int main() {}",
        )
        assert result is None

    def test_llm_returns_invalid_source(self) -> None:
        """When LLM returns something without entry point, it's rejected."""
        stage = CompileStage()
        result = stage._ask_llm_for_fix(
            llm=MagicMock(complete=MagicMock(return_value="this is not valid code")),
            compile_cmd="clang++ foo.cpp",
            source_file="foo.cpp",
            error_output="error: undeclared",
            source_code='extern "C" int LLVMFuzzerTestOneInput(...) { return 0; }',
        )
        assert result is None

    def test_llm_strips_markdown_fences(self) -> None:
        """LLM response with markdown fences is cleaned up."""
        stage = CompileStage()
        response = (
            '```cpp\n'
            '#include <stdint.h>\n'
            'extern "C" int LLVMFuzzerTestOneInput(const uint8_t *d, size_t s) { return 0; }\n'
            '```'
        )
        result = stage._ask_llm_for_fix(
            llm=MagicMock(complete=MagicMock(return_value=response)),
            compile_cmd="clang++ foo.cpp",
            source_file="foo.cpp",
            error_output="error",
            source_code="old code",
        )
        assert result is not None
        assert "```" not in result
        assert "LLVMFuzzerTestOneInput" in result

    def test_llm_exception_returns_none(self) -> None:
        """When LLM raises an exception, _ask_llm_for_fix returns None."""
        stage = CompileStage()
        result = stage._ask_llm_for_fix(
            llm=MagicMock(complete=MagicMock(side_effect=RuntimeError("API error"))),
            compile_cmd="clang++ foo.cpp",
            source_file="foo.cpp",
            error_output="error",
            source_code="code",
        )
        assert result is None

    def test_no_llm_no_retry(self, tmp_path: Path) -> None:
        """When compile_use_llm is False, no retries are attempted."""
        ctx = _make_context(
            tmp_path,
            harnesses=[_make_harness("f")],
            extra_config={"compile_use_llm": False},
        )
        stage = CompileStage()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error", stdout="")
            result = stage.execute(ctx)

        assert result.success is False
        # Only one call: no retries
        assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# CompileStage: can_skip
# ---------------------------------------------------------------------------


class TestCompileStageCanSkip:
    def test_can_skip_with_binaries(self, tmp_path: Path) -> None:
        binaries_dir = tmp_path / "fuzz_binaries"
        binaries_dir.mkdir()
        (binaries_dir / "fuzz_foo").write_text("binary")
        ctx = PipelineContext(binaries_dir=binaries_dir)
        stage = CompileStage()
        assert stage.can_skip(ctx) is True

    def test_cannot_skip_empty_dir(self, tmp_path: Path) -> None:
        binaries_dir = tmp_path / "fuzz_binaries"
        binaries_dir.mkdir()
        ctx = PipelineContext(binaries_dir=binaries_dir)
        stage = CompileStage()
        assert stage.can_skip(ctx) is False

    def test_cannot_skip_no_dir(self) -> None:
        ctx = PipelineContext()
        stage = CompileStage()
        assert stage.can_skip(ctx) is False

    def test_cannot_skip_dir_with_only_sources(self, tmp_path: Path) -> None:
        binaries_dir = tmp_path / "fuzz_binaries"
        binaries_dir.mkdir()
        (binaries_dir / "fuzz_foo.cpp").write_text("source")
        ctx = PipelineContext(binaries_dir=binaries_dir)
        stage = CompileStage()
        assert stage.can_skip(ctx) is False


# ---------------------------------------------------------------------------
# CompileStage: _build_compile_cmd
# ---------------------------------------------------------------------------


class TestBuildCompileCmd:
    def test_basic_cmd(self, tmp_path: Path) -> None:
        cmd = CompileStage._build_compile_cmd(
            "clang++",
            tmp_path / "foo.cpp",
            tmp_path / "foo",
            ["-g"],
            [],
            [],
        )
        assert cmd[0] == "clang++"
        assert "-g" in cmd
        assert str(tmp_path / "foo.cpp") in cmd
        assert "-o" in cmd
        assert str(tmp_path / "foo") in cmd

    def test_with_all_flags(self, tmp_path: Path) -> None:
        cmd = CompileStage._build_compile_cmd(
            "clang++",
            tmp_path / "foo.cpp",
            tmp_path / "foo",
            ["-fsanitize=fuzzer", "-g"],
            ["-DTEST"],
            ["-L/usr/lib", "-lfoo"],
        )
        assert "-fsanitize=fuzzer" in cmd
        assert "-DTEST" in cmd
        assert "-L/usr/lib" in cmd
        assert "-lfoo" in cmd


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCompileCLI:
    def test_cli_compile_requires_targets(self) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["compile"])
        assert result.exit_code != 0
        assert "Missing" in result.output or "required" in result.output.lower() or "Error" in result.output

    def test_cli_compile_help(self) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["compile", "--help"])
        assert result.exit_code == 0
        assert "--targets" in result.output
        assert "--compiler" in result.output
        assert "--retry" in result.output
        assert "--no-llm" in result.output
        assert "--prefix" in result.output

    def test_cli_compile_no_sources(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["compile", "--targets", str(tmp_path)])
        assert result.exit_code != 0
        assert "No harness source files" in result.output

    def test_cli_compile_success(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from futagassist.cli import main

        # Write a harness source
        source = tmp_path / "harness_foo.cpp"
        source.write_text(
            '#include <stdint.h>\n'
            'extern "C" int LLVMFuzzerTestOneInput(const uint8_t *d, size_t s) { return 0; }\n'
        )

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            result = runner.invoke(main, [
                "compile",
                "--targets", str(tmp_path),
                "--no-llm",
            ])

        assert result.exit_code == 0
        assert "Compiled" in result.output


# ---------------------------------------------------------------------------
# Named-constant sanity checks
# ---------------------------------------------------------------------------


class TestCompileStageConstants:
    """Verify named constants are importable and have sensible values."""

    def test_max_compiler_error_lines(self) -> None:
        assert isinstance(MAX_COMPILER_ERROR_LINES, int)
        assert MAX_COMPILER_ERROR_LINES > 0

    def test_max_backoff_seconds(self) -> None:
        assert isinstance(MAX_BACKOFF_SECONDS, int)
        assert MAX_BACKOFF_SECONDS > 0

    def test_default_compile_timeout(self) -> None:
        assert isinstance(DEFAULT_COMPILE_TIMEOUT, int)
        assert DEFAULT_COMPILE_TIMEOUT > 0

    def test_max_error_output_chars(self) -> None:
        assert isinstance(MAX_ERROR_OUTPUT_CHARS, int)
        assert MAX_ERROR_OUTPUT_CHARS > 0

    def test_max_source_code_chars(self) -> None:
        assert isinstance(MAX_SOURCE_CODE_CHARS, int)
        assert MAX_SOURCE_CODE_CHARS > 0

    def test_parse_compiler_errors_respects_cap(self) -> None:
        """_parse_compiler_errors should cap results at MAX_COMPILER_ERROR_LINES."""
        lines = "\n".join(f"file.cpp:1: error: problem {i}" for i in range(50))
        errors = _parse_compiler_errors(lines)
        assert len(errors) == MAX_COMPILER_ERROR_LINES
