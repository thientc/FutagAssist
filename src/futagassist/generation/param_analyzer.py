"""Parameter analyzer: analyzes C/C++ parameter types for FuzzedDataProvider generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ParamKind(Enum):
    """Kind of parameter for harness generation."""

    INTEGRAL = "integral"  # int, size_t, uint32_t, etc.
    FLOATING = "floating"  # float, double
    BOOL = "bool"
    CHAR = "char"  # single char
    STRING = "string"  # char*, const char*
    BUFFER = "buffer"  # uint8_t*, void*, byte array
    POINTER = "pointer"  # other pointer types
    STRUCT = "struct"  # struct/class types
    ENUM = "enum"
    UNKNOWN = "unknown"


@dataclass
class ParsedParam:
    """Parsed parameter information."""

    name: str
    type_str: str
    kind: ParamKind
    is_const: bool = False
    is_pointer: bool = False
    is_array: bool = False
    array_size: int | None = None
    base_type: str = ""
    # For buffer+size pairs
    size_param: str | None = None


# Type patterns for classification
INTEGRAL_TYPES = {
    "int", "short", "long", "char",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "size_t", "ssize_t", "ptrdiff_t",
    "unsigned", "signed",
    "uchar", "ushort", "uint", "ulong",
    "BYTE", "WORD", "DWORD", "QWORD",
}

FLOATING_TYPES = {"float", "double", "long double"}

BUFFER_POINTER_TYPES = {
    "uint8_t", "int8_t", "char", "unsigned char",
    "void", "BYTE", "byte",
}

SIZE_PARAM_PATTERNS = [
    r".*_len$", r".*_size$", r".*_length$", r".*_count$",
    r"^len$", r"^size$", r"^length$", r"^count$", r"^n$", r"^num.*",
    r"^cb.*",  # Windows convention: cbSize, cbData
]


def parse_parameter(param_str: str) -> ParsedParam:
    """Parse a C/C++ parameter string into ParsedParam."""
    param_str = param_str.strip()
    if not param_str:
        return ParsedParam(name="", type_str="", kind=ParamKind.UNKNOWN)

    # Handle array notation: type name[size]
    array_match = re.search(r"\[(\d*)\]", param_str)
    array_size = None
    is_array = False
    if array_match:
        is_array = True
        if array_match.group(1):
            array_size = int(array_match.group(1))
        param_str = param_str[:array_match.start()].strip()

    # Split into type and name
    # Handle cases like "const char *name" or "int x"
    parts = param_str.rsplit(None, 1)
    if len(parts) == 1:
        # Could be just a type (unnamed param) or just a name
        type_str = parts[0]
        name = ""
    else:
        # Last part might be the name, but handle pointer notation
        type_str = parts[0]
        name = parts[1]

        # Handle "char* name" vs "char *name"
        if name.startswith("*"):
            type_str += " *"
            name = name[1:]
        elif type_str.endswith("*"):
            pass  # Already correct

    # Clean up type string
    type_str = type_str.strip()
    is_const = "const" in type_str
    is_pointer = "*" in type_str or is_array

    # Get base type (remove const, *, &)
    base_type = type_str.replace("const", "").replace("*", "").replace("&", "").strip()
    base_type = re.sub(r"\s+", " ", base_type)

    # Classify the parameter
    kind = _classify_type(base_type, is_pointer, is_array)

    return ParsedParam(
        name=name,
        type_str=type_str,
        kind=kind,
        is_const=is_const,
        is_pointer=is_pointer,
        is_array=is_array,
        array_size=array_size,
        base_type=base_type,
    )


def _classify_type(base_type: str, is_pointer: bool, is_array: bool) -> ParamKind:
    """Classify a type into ParamKind."""
    base_lower = base_type.lower()

    if base_type == "bool" or base_lower == "_bool":
        return ParamKind.BOOL

    if base_type in FLOATING_TYPES:
        return ParamKind.FLOATING

    # Check for string types
    if is_pointer and base_type in ("char", "wchar_t"):
        return ParamKind.STRING

    # Check for buffer types
    if is_pointer or is_array:
        if base_type in BUFFER_POINTER_TYPES:
            return ParamKind.BUFFER
        # Other pointer types
        if base_type in INTEGRAL_TYPES or base_type in FLOATING_TYPES:
            return ParamKind.BUFFER
        return ParamKind.POINTER

    # Check for integral types
    # Handle multi-word types like "unsigned int", "long long"
    base_words = set(base_type.split())
    if base_words & INTEGRAL_TYPES:
        return ParamKind.INTEGRAL

    # Check for enum keyword
    if "enum" in base_lower:
        return ParamKind.ENUM

    # Check for struct/class
    if "struct" in base_lower or "class" in base_lower:
        return ParamKind.STRUCT

    # Single char (not pointer)
    if base_type == "char":
        return ParamKind.CHAR

    return ParamKind.UNKNOWN


def is_size_param(name: str) -> bool:
    """Check if parameter name suggests it's a size/length parameter."""
    name_lower = name.lower()
    for pattern in SIZE_PARAM_PATTERNS:
        if re.match(pattern, name_lower):
            return True
    return False


def find_buffer_size_pairs(params: list[ParsedParam]) -> list[tuple[ParsedParam, ParsedParam | None]]:
    """Find buffer parameters and their associated size parameters."""
    pairs: list[tuple[ParsedParam, ParsedParam | None]] = []

    for i, param in enumerate(params):
        if param.kind in (ParamKind.BUFFER, ParamKind.STRING):
            # Look for a size parameter after this one
            size_param = None
            for j in range(i + 1, min(i + 3, len(params))):
                if params[j].kind == ParamKind.INTEGRAL and is_size_param(params[j].name):
                    size_param = params[j]
                    param.size_param = size_param.name
                    break
            pairs.append((param, size_param))
        elif param.kind == ParamKind.INTEGRAL and is_size_param(param.name):
            # Skip - will be handled as part of a pair
            continue
        else:
            pairs.append((param, None))

    return pairs


def generate_fdp_consume(
    param: ParsedParam,
    size_param: ParsedParam | None = None,
    name_prefix: str = "",
) -> tuple[str, str, str | None]:
    """Generate FuzzedDataProvider consume code for a parameter.

    Returns: (declaration_code, variable_name, size_variable_name or None)
    """
    name = name_prefix + (param.name or "arg")
    size_name = name_prefix + size_param.name if size_param else None

    if param.kind == ParamKind.BOOL:
        return f"    bool {name} = fdp.ConsumeBool();", name, None

    if param.kind == ParamKind.CHAR:
        return f"    char {name} = fdp.ConsumeIntegral<char>();", name, None

    if param.kind == ParamKind.INTEGRAL:
        # Map to appropriate type
        cpp_type = _normalize_integral_type(param.base_type)
        return f"    {cpp_type} {name} = fdp.ConsumeIntegral<{cpp_type}>();", name, None

    if param.kind == ParamKind.FLOATING:
        cpp_type = param.base_type
        return f"    {cpp_type} {name} = fdp.ConsumeFloatingPoint<{cpp_type}>();", name, None

    if param.kind == ParamKind.STRING:
        if size_param:
            # String with explicit length parameter
            code = f"    size_t {size_name} = fdp.ConsumeIntegralInRange<size_t>(0, fdp.remaining_bytes());\n"
            code += f"    std::string {name}_str = fdp.ConsumeBytesAsString({size_name});\n"
            if param.is_const:
                code += f"    const char* {name} = {name}_str.c_str();"
            else:
                code += f"    std::vector<char> {name}_vec({name}_str.begin(), {name}_str.end());\n"
                code += f"    {name}_vec.push_back('\\0');\n"
                code += f"    char* {name} = {name}_vec.data();"
            return code, name, size_name
        elif param.is_const:
            # Const string - can use c_str() directly
            code = f"    std::string {name}_str = fdp.ConsumeRandomLengthString(1024);\n"
            code += f"    const char* {name} = {name}_str.c_str();"
            return code, name, None
        else:
            # Mutable string - need to copy
            code = f"    std::string {name}_str = fdp.ConsumeRandomLengthString(1024);\n"
            code += f"    std::vector<char> {name}_vec({name}_str.begin(), {name}_str.end());\n"
            code += f"    {name}_vec.push_back('\\0');\n"
            code += f"    char* {name} = {name}_vec.data();"
            return code, name, None

    if param.kind == ParamKind.BUFFER:
        if size_param:
            # Buffer with known size parameter
            code = f"    size_t {size_name} = fdp.ConsumeIntegralInRange<size_t>(0, fdp.remaining_bytes());\n"
            code += f"    std::vector<uint8_t> {name}_vec = fdp.ConsumeBytes<uint8_t>({size_name});\n"
            if param.is_const:
                code += f"    const uint8_t* {name} = {name}_vec.data();"
            else:
                code += f"    uint8_t* {name} = {name}_vec.data();"
            return code, name, size_name
        else:
            # Buffer without explicit size - consume remaining or fixed amount
            code = f"    std::vector<uint8_t> {name}_vec = fdp.ConsumeBytes<uint8_t>(fdp.remaining_bytes());\n"
            code += f"    size_t {name}_size = {name}_vec.size();\n"
            if param.is_const:
                code += f"    const uint8_t* {name} = {name}_vec.data();"
            else:
                code += f"    uint8_t* {name} = {name}_vec.data();"
            return code, name, None

    if param.kind == ParamKind.POINTER:
        # Generic pointer - hard to fuzz, use nullptr or allocate
        return f"    {param.type_str} {name} = nullptr;  // TODO: allocate if needed", name, None

    if param.kind == ParamKind.ENUM:
        # Enum - consume as integral and cast
        return f"    auto {name} = static_cast<{param.base_type}>(fdp.ConsumeIntegral<int>());", name, None

    # Unknown - just declare
    return f"    // TODO: provide value for {param.type_str} {name}", name, None


def _normalize_integral_type(type_str: str) -> str:
    """Normalize integral type to standard C++ type."""
    type_map = {
        "unsigned": "unsigned int",
        "signed": "int",
        "uchar": "unsigned char",
        "ushort": "unsigned short",
        "uint": "unsigned int",
        "ulong": "unsigned long",
        "BYTE": "uint8_t",
        "WORD": "uint16_t",
        "DWORD": "uint32_t",
        "QWORD": "uint64_t",
    }
    return type_map.get(type_str, type_str)
