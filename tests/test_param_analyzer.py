"""Tests for the parameter analyzer module."""

import pytest

from futagassist.generation.param_analyzer import (
    ParsedParam,
    ParamKind,
    find_buffer_size_pairs,
    generate_fdp_consume,
    is_size_param,
    parse_parameter,
)


class TestParseParameter:
    """Tests for parse_parameter function."""

    def test_parse_simple_int(self):
        """Parse simple int parameter."""
        result = parse_parameter("int x")
        assert result.name == "x"
        assert result.kind == ParamKind.INTEGRAL
        assert result.base_type == "int"
        assert not result.is_pointer

    def test_parse_size_t(self):
        """Parse size_t parameter."""
        result = parse_parameter("size_t len")
        assert result.name == "len"
        assert result.kind == ParamKind.INTEGRAL
        assert result.base_type == "size_t"

    def test_parse_const_char_pointer(self):
        """Parse const char* (string) parameter."""
        result = parse_parameter("const char* str")
        assert result.name == "str"
        assert result.kind == ParamKind.STRING
        assert result.is_const
        assert result.is_pointer

    def test_parse_uint8_t_pointer(self):
        """Parse uint8_t* (buffer) parameter."""
        result = parse_parameter("uint8_t* buf")
        assert result.name == "buf"
        assert result.kind == ParamKind.BUFFER
        assert result.is_pointer

    def test_parse_void_pointer(self):
        """Parse void* (buffer) parameter."""
        result = parse_parameter("void * pv")
        assert result.name == "pv"
        assert result.kind == ParamKind.BUFFER
        assert result.is_pointer

    def test_parse_custom_pointer(self):
        """Parse custom type pointer."""
        result = parse_parameter("display * dp")
        assert result.name == "dp"
        assert result.kind == ParamKind.POINTER
        assert result.is_pointer
        assert result.base_type == "display"

    def test_parse_bool(self):
        """Parse bool parameter."""
        result = parse_parameter("bool flag")
        assert result.name == "flag"
        assert result.kind == ParamKind.BOOL

    def test_parse_float(self):
        """Parse float parameter."""
        result = parse_parameter("float val")
        assert result.name == "val"
        assert result.kind == ParamKind.FLOATING

    def test_parse_double(self):
        """Parse double parameter."""
        result = parse_parameter("double d")
        assert result.name == "d"
        assert result.kind == ParamKind.FLOATING

    def test_parse_unsigned_int(self):
        """Parse unsigned int parameter."""
        result = parse_parameter("unsigned int n")
        assert result.name == "n"
        assert result.kind == ParamKind.INTEGRAL

    def test_parse_array(self):
        """Parse array parameter."""
        result = parse_parameter("char buf[256]")
        assert result.name == "buf"
        assert result.is_array
        assert result.array_size == 256


class TestIsSizeParam:
    """Tests for is_size_param function."""

    def test_len_suffix(self):
        assert is_size_param("buffer_len")
        assert is_size_param("data_len")

    def test_size_suffix(self):
        assert is_size_param("buffer_size")
        assert is_size_param("data_size")

    def test_length_suffix(self):
        assert is_size_param("str_length")

    def test_exact_names(self):
        assert is_size_param("len")
        assert is_size_param("size")
        assert is_size_param("length")
        assert is_size_param("count")
        assert is_size_param("n")

    def test_num_prefix(self):
        assert is_size_param("num_elements")
        assert is_size_param("numBytes")

    def test_not_size_param(self):
        assert not is_size_param("buffer")
        assert not is_size_param("data")
        assert not is_size_param("name")


class TestFindBufferSizePairs:
    """Tests for find_buffer_size_pairs function."""

    def test_buffer_with_size(self):
        """Test detection of buffer+size pair."""
        params = [
            parse_parameter("void * pv"),
            parse_parameter("size_t size"),
        ]
        pairs = find_buffer_size_pairs(params)
        assert len(pairs) == 1
        assert pairs[0][0].name == "pv"
        assert pairs[0][1].name == "size"

    def test_string_with_len(self):
        """Test detection of string+length pair."""
        params = [
            parse_parameter("const char* str"),
            parse_parameter("size_t len"),
        ]
        pairs = find_buffer_size_pairs(params)
        assert len(pairs) == 1
        assert pairs[0][0].name == "str"
        assert pairs[0][1].name == "len"

    def test_no_size_param(self):
        """Test buffer without size parameter."""
        params = [
            parse_parameter("uint8_t* data"),
            parse_parameter("int flags"),
        ]
        pairs = find_buffer_size_pairs(params)
        assert len(pairs) == 2
        assert pairs[0][0].name == "data"
        assert pairs[0][1] is None  # No size param

    def test_multiple_pairs(self):
        """Test multiple buffer+size pairs."""
        params = [
            parse_parameter("const char* input"),
            parse_parameter("size_t input_len"),
            parse_parameter("char* output"),
            parse_parameter("size_t output_size"),
        ]
        pairs = find_buffer_size_pairs(params)
        # Should find 2 buffer+size pairs
        buffers = [(p[0].name, p[1].name if p[1] else None) for p in pairs]
        assert ("input", "input_len") in buffers
        assert ("output", "output_size") in buffers


class TestGenerateFdpConsume:
    """Tests for generate_fdp_consume function."""

    def test_integral(self):
        """Test integral parameter generation."""
        param = parse_parameter("int x")
        code, var_name, size_name = generate_fdp_consume(param)
        assert "ConsumeIntegral<int>()" in code
        assert var_name == "x"
        assert size_name is None

    def test_bool(self):
        """Test bool parameter generation."""
        param = parse_parameter("bool flag")
        code, var_name, size_name = generate_fdp_consume(param)
        assert "ConsumeBool()" in code
        assert var_name == "flag"

    def test_float(self):
        """Test float parameter generation."""
        param = parse_parameter("float val")
        code, var_name, size_name = generate_fdp_consume(param)
        assert "ConsumeFloatingPoint<float>()" in code

    def test_const_string(self):
        """Test const char* parameter generation."""
        param = parse_parameter("const char* str")
        code, var_name, size_name = generate_fdp_consume(param)
        assert "ConsumeRandomLengthString" in code
        assert "c_str()" in code
        assert var_name == "str"

    def test_buffer_with_size(self):
        """Test buffer+size parameter generation."""
        buf_param = parse_parameter("uint8_t* data")
        size_param = parse_parameter("size_t size")
        code, var_name, size_name = generate_fdp_consume(buf_param, size_param)
        assert "ConsumeIntegralInRange<size_t>" in code
        assert "ConsumeBytes<uint8_t>" in code
        assert var_name == "data"
        assert size_name == "size"

    def test_string_with_length(self):
        """Test string+length parameter generation."""
        str_param = parse_parameter("const char* str")
        len_param = parse_parameter("size_t len")
        code, var_name, size_name = generate_fdp_consume(str_param, len_param)
        assert "ConsumeBytesAsString" in code
        assert var_name == "str"
        assert size_name == "len"

    def test_name_prefix(self):
        """Test name prefix for avoiding collisions."""
        param = parse_parameter("int x")
        code, var_name, size_name = generate_fdp_consume(param, name_prefix="step0_")
        assert "step0_x" in code
        assert var_name == "step0_x"

    def test_pointer_type(self):
        """Test custom pointer type generation."""
        param = parse_parameter("MyStruct* ptr")
        code, var_name, size_name = generate_fdp_consume(param)
        assert "nullptr" in code
        assert "TODO" in code
