/**
 * @name Fuzz target candidates
 * @description Identify functions that are excellent candidates for fuzzing.
 *              These take raw input data (buffer + size, strings, file handles)
 *              and are likely entry points for parsing, decoding, or processing.
 * @kind problem
 * @id futagassist/fuzz-targets
 */
import cpp

/**
 * True if parameter type is a byte/char pointer (input buffer).
 */
predicate isBytePointer(Parameter p) {
  exists(PointerType pt |
    pt = p.getType().getUnspecifiedType() and
    (
      pt.getBaseType().getUnspecifiedType() instanceof CharType or
      pt.getBaseType().getUnspecifiedType() instanceof UnsignedCharType or
      pt.getBaseType().getUnspecifiedType().(TypedefType).getName() = "uint8_t"
    )
  )
}

/**
 * True if parameter type is void pointer (generic buffer).
 */
predicate isVoidPointer(Parameter p) {
  exists(PointerType pt |
    pt = p.getType().getUnspecifiedType() and
    pt.getBaseType().getUnspecifiedType() instanceof VoidType
  )
}

/**
 * True if parameter looks like a size parameter by name and type.
 */
predicate isSizeParameter(Parameter p) {
  p.getName().regexpMatch("(?i).*(size|len|length|count|num|n|sz|bytes).*") and
  (
    p.getType().getUnspecifiedType() instanceof IntegralType or
    p.getType().getUnspecifiedType().(TypedefType).getName().regexpMatch("size_t|ssize_t|uint32_t|int32_t|uint64_t|int64_t")
  )
}

/**
 * True if function takes a (buffer, size) pair - ideal for fuzzing.
 */
predicate takesBufferAndSize(Function f) {
  exists(Parameter bufParam, Parameter sizeParam, int bufIdx, int sizeIdx |
    bufParam = f.getParameter(bufIdx) and
    sizeParam = f.getParameter(sizeIdx) and
    (isBytePointer(bufParam) or isVoidPointer(bufParam)) and
    isSizeParameter(sizeParam) and
    // Size param should be adjacent or close to buffer param
    (sizeIdx = bufIdx + 1 or sizeIdx = bufIdx - 1 or sizeIdx = bufIdx + 2)
  )
}

/**
 * True if function takes a C string (char*) parameter.
 */
predicate takesCString(Function f) {
  exists(Parameter p |
    p = f.getAParameter() and
    isBytePointer(p) and
    not exists(Parameter sizeParam |
      sizeParam = f.getAParameter() and isSizeParameter(sizeParam)
    )
  )
}

/**
 * True if function takes a FILE* parameter.
 */
predicate takesFileHandle(Function f) {
  exists(Parameter p |
    p = f.getAParameter() and
    (
      p.getType().toString().regexpMatch(".*FILE.*\\*.*") or
      p.getType().toString() = "int" and p.getName().regexpMatch("(?i).*(fd|file|handle).*")
    )
  )
}

/**
 * True if function name suggests input processing.
 */
predicate isInputProcessor(Function f) {
  f.getName().regexpMatch("(?i)^(parse|read|decode|load|deserialize|from_|input_|process|handle|recv|import|scan|lex|tokenize).*") or
  f.getName().regexpMatch("(?i).*(parse|read|decode|load|deserialize|from_buffer|from_bytes|from_string|from_file)$")
}

/**
 * True if function is declared in a header (public API).
 */
predicate isPublicAPI(Function f) {
  exists(FunctionDeclarationEntry fde |
    fde.getFunction() = f and
    fde.getFile().getExtension().regexpMatch("h|hpp|hxx|H")
  )
}

/**
 * Get parameter info as "type name" string.
 */
string getParamInfo(Parameter p) {
  result = p.getType().toString() + " " + p.getName()
}

/**
 * Concatenate all parameters.
 */
string getParamsSignature(Function f) {
  result = concat(int i, Parameter p |
    p = f.getParameter(i)
  |
    getParamInfo(p), ", " order by i
  )
}

/**
 * Classify the fuzz target type.
 */
string fuzzTargetType(Function f) {
  if takesBufferAndSize(f) then result = "buffer_size"
  else if takesCString(f) then result = "cstring"
  else if takesFileHandle(f) then result = "file"
  else result = "other"
}

/**
 * Compute fuzz priority score.
 */
int fuzzScore(Function f) {
  result = 
    (if takesBufferAndSize(f) then 10 else 0) +
    (if takesCString(f) then 5 else 0) +
    (if isInputProcessor(f) then 5 else 0) +
    (if isPublicAPI(f) then 3 else 0) +
    (if not f.isStatic() then 2 else 0)
}

// String-returning wrappers for select
string bufferSizeStr(Function f) { if takesBufferAndSize(f) then result = "true" else result = "false" }
string cstringStr(Function f) { if takesCString(f) then result = "true" else result = "false" }
string fileHandleStr(Function f) { if takesFileHandle(f) then result = "true" else result = "false" }
string inputProcessorStr(Function f) { if isInputProcessor(f) then result = "true" else result = "false" }
string publicAPIStr(Function f) { if isPublicAPI(f) then result = "true" else result = "false" }

from Function f, int score, string targetType
where
  f.getFile().fromSource() and
  not f.isCompilerGenerated() and
  f.hasDefinition() and
  score = fuzzScore(f) and
  targetType = fuzzTargetType(f) and
  // Only functions with fuzz potential
  (takesBufferAndSize(f) or takesCString(f) or takesFileHandle(f) or isInputProcessor(f)) and
  score >= 5
select
  f.getFile().getRelativePath() as file_path,
  f.getLocation().getStartLine() as line,
  f.getName() as name,
  f.getQualifiedName() as qualified_name,
  f.getType().toString() as return_type,
  f.getNumberOfParameters() as param_count,
  getParamsSignature(f) as parameters,
  targetType as fuzz_type,
  bufferSizeStr(f) as buffer_size_api,
  cstringStr(f) as cstring_api,
  fileHandleStr(f) as file_api,
  inputProcessorStr(f) as input_processor,
  publicAPIStr(f) as public_api,
  score as fuzz_score
order by score desc
