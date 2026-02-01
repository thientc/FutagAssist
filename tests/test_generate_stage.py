"""Tests for the generate stage."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from futagassist.core.schema import (
    FunctionInfo,
    GeneratedHarness,
    PipelineContext,
    UsageContext,
)
from futagassist.stages.generate_stage import GenerateStage


@pytest.fixture
def mock_registry():
    """Create a mock registry."""
    registry = MagicMock()
    registry.list_available.return_value = {
        "stages": ["generate"],
        "llm_providers": [],
        "language_analyzers": ["cpp"],
    }
    registry.get_stage.return_value = GenerateStage()
    return registry


@pytest.fixture
def mock_config_manager():
    """Create a mock config manager."""
    config_manager = MagicMock()
    config_manager.config.language = "cpp"
    config_manager.config.llm_provider = "openai"
    config_manager.env = {}
    return config_manager


@pytest.fixture
def sample_functions():
    """Create sample function info for testing."""
    return [
        FunctionInfo(
            name="parse_data",
            signature="int parse_data(const char* data, size_t size)",
            return_type="int",
            parameters=["const char* data", "size_t size"],
            file_path="parser.c",
            line=42,
        ),
        FunctionInfo(
            name="process_buffer",
            signature="void process_buffer(uint8_t* buf, int len)",
            return_type="void",
            parameters=["uint8_t* buf", "int len"],
            file_path="processor.c",
            line=100,
        ),
    ]


class TestGenerateStage:
    """Tests for GenerateStage."""

    def test_generate_stage_no_functions(self, mock_registry, mock_config_manager):
        """Test that generate stage fails when no functions in context."""
        ctx = PipelineContext(
            functions=[],
            config={
                "registry": mock_registry,
                "config_manager": mock_config_manager,
            },
        )
        stage = GenerateStage()
        result = stage.execute(ctx)

        assert not result.success
        assert "No functions" in result.message

    def test_generate_stage_no_registry(self):
        """Test that generate stage fails without registry."""
        ctx = PipelineContext(
            functions=[FunctionInfo(name="test", signature="void test()")],
            config={},
        )
        stage = GenerateStage()
        result = stage.execute(ctx)

        assert not result.success
        assert "registry" in result.message.lower()

    def test_generate_stage_success_template_only(
        self, mock_registry, mock_config_manager, sample_functions, tmp_path
    ):
        """Test successful generation without LLM (template only)."""
        ctx = PipelineContext(
            functions=sample_functions,
            language="cpp",
            config={
                "registry": mock_registry,
                "config_manager": mock_config_manager,
                "generate_output": str(tmp_path),
                "use_llm": False,
                "validate": True,
                "write_harnesses": True,
            },
        )
        stage = GenerateStage()
        result = stage.execute(ctx)

        assert result.success
        assert "generated_harnesses" in result.data
        harnesses = result.data["generated_harnesses"]
        assert len(harnesses) == 2

        # Check that files were written
        written_paths = result.data.get("written_paths", [])
        assert len(written_paths) == 2

        # Check files exist
        for path_str in written_paths:
            assert Path(path_str).exists()

    def test_generate_stage_with_usage_contexts(
        self, mock_registry, mock_config_manager, sample_functions, tmp_path
    ):
        """Test generation with usage contexts."""
        usage_contexts = [
            UsageContext(
                name="init_process",
                calls=["parse_data", "process_buffer"],
            ),
        ]

        ctx = PipelineContext(
            functions=sample_functions,
            usage_contexts=usage_contexts,
            language="cpp",
            config={
                "registry": mock_registry,
                "config_manager": mock_config_manager,
                "generate_output": str(tmp_path),
                "use_llm": False,
                "validate": False,
                "write_harnesses": True,
            },
        )
        stage = GenerateStage()
        result = stage.execute(ctx)

        assert result.success
        harnesses = result.data["generated_harnesses"]
        # 2 functions + 1 sequence
        assert len(harnesses) == 3

    def test_generate_stage_max_targets(
        self, mock_registry, mock_config_manager, sample_functions, tmp_path
    ):
        """Test that max_targets limits generation."""
        ctx = PipelineContext(
            functions=sample_functions,
            language="cpp",
            config={
                "registry": mock_registry,
                "config_manager": mock_config_manager,
                "generate_output": str(tmp_path),
                "use_llm": False,
                "validate": False,
                "max_targets": 1,
                "write_harnesses": True,
            },
        )
        stage = GenerateStage()
        result = stage.execute(ctx)

        assert result.success
        harnesses = result.data["generated_harnesses"]
        assert len(harnesses) == 1

    def test_generate_stage_can_skip_with_existing_harnesses(
        self, sample_functions, tmp_path
    ):
        """Test can_skip when harnesses already exist."""
        # Create some harness files
        (tmp_path / "harness_test.cpp").write_text("// test")

        ctx = PipelineContext(
            fuzz_targets_dir=tmp_path,
        )
        stage = GenerateStage()

        assert stage.can_skip(ctx)

    def test_generate_stage_cannot_skip_without_harnesses(self):
        """Test can_skip returns False when no harnesses."""
        ctx = PipelineContext()
        stage = GenerateStage()

        assert not stage.can_skip(ctx)


class TestHarnessGenerator:
    """Tests for HarnessGenerator."""

    def test_generate_for_function_template(self, sample_functions):
        """Test template-based harness generation."""
        from futagassist.generation.harness_generator import HarnessGenerator

        generator = HarnessGenerator(llm=None, language="cpp")
        harness = generator.generate_for_function(sample_functions[0], use_llm=False)

        assert harness.function_name == "parse_data"
        assert "LLVMFuzzerTestOneInput" in harness.source_code
        assert harness.file_path.startswith("harness_")
        assert harness.file_path.endswith(".cpp")

    def test_generate_for_function_with_llm(self, sample_functions):
        """Test LLM-based harness generation."""
        from futagassist.generation.harness_generator import HarnessGenerator

        mock_llm = MagicMock()
        mock_llm.complete.return_value = '''```cpp
#include <stdint.h>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    parse_data((const char*)data, size);
    return 0;
}
```'''

        generator = HarnessGenerator(llm=mock_llm, language="cpp")
        harness = generator.generate_for_function(sample_functions[0], use_llm=True)

        assert harness.function_name == "parse_data"
        assert "LLVMFuzzerTestOneInput" in harness.source_code
        mock_llm.complete.assert_called_once()

    def test_generate_batch(self, sample_functions):
        """Test batch generation."""
        from futagassist.generation.harness_generator import HarnessGenerator

        generator = HarnessGenerator(llm=None, language="cpp")
        harnesses = generator.generate_batch(sample_functions, use_llm=False)

        assert len(harnesses) == 2
        assert all(isinstance(h, GeneratedHarness) for h in harnesses)

    def test_write_harnesses(self, sample_functions, tmp_path):
        """Test writing harnesses to disk."""
        from futagassist.generation.harness_generator import HarnessGenerator

        generator = HarnessGenerator(llm=None, language="cpp", output_dir=tmp_path)
        harnesses = generator.generate_batch(sample_functions, use_llm=False)
        paths = generator.write_harnesses(harnesses)

        assert len(paths) == 2
        for path in paths:
            assert path.exists()
            content = path.read_text()
            assert "LLVMFuzzerTestOneInput" in content


class TestSyntaxValidator:
    """Tests for SyntaxValidator."""

    def test_quick_validate_valid_harness(self):
        """Test quick validation of valid harness."""
        from futagassist.generation.syntax_validator import SyntaxValidator

        harness = GeneratedHarness(
            function_name="test",
            source_code='''
#include <stdint.h>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    return 0;
}
''',
        )

        validator = SyntaxValidator()
        result = validator.quick_validate(harness)

        assert result.is_valid
        assert len(result.validation_errors) == 0

    def test_quick_validate_missing_entry_point(self):
        """Test quick validation catches missing entry point."""
        from futagassist.generation.syntax_validator import SyntaxValidator

        harness = GeneratedHarness(
            function_name="test",
            source_code='''
#include <stdint.h>
int main() {
    return 0;
}
''',
        )

        validator = SyntaxValidator()
        result = validator.quick_validate(harness)

        assert not result.is_valid
        assert any("LLVMFuzzerTestOneInput" in e for e in result.validation_errors)

    def test_quick_validate_unbalanced_braces(self):
        """Test quick validation catches unbalanced braces."""
        from futagassist.generation.syntax_validator import SyntaxValidator

        harness = GeneratedHarness(
            function_name="test",
            source_code='''
#include <stdint.h>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    return 0;
''',
        )

        validator = SyntaxValidator()
        result = validator.quick_validate(harness)

        assert not result.is_valid
        assert any("brace" in e.lower() for e in result.validation_errors)

    def test_check_basic_structure(self):
        """Test basic structure checks."""
        from futagassist.generation.syntax_validator import SyntaxValidator

        validator = SyntaxValidator()

        # Valid harness
        harness = GeneratedHarness(
            function_name="test",
            source_code='#include <x>\nLLVMFuzzerTestOneInput() { return 0; }',
        )
        errors = validator.check_basic_structure(harness)
        assert len(errors) == 0

        # Missing include
        harness.source_code = 'LLVMFuzzerTestOneInput() { return 0; }'
        errors = validator.check_basic_structure(harness)
        assert any("include" in e.lower() for e in errors)
