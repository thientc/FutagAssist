/**
 * @name API functions suitable for fuzzing
 * @description Identify public API functions that are good candidates for fuzz targets.
 *              These include: functions declared in headers, extern functions, functions
 *              with external linkage, and functions that process input data.
 * @kind problem
 * @id futagassist/api-functions
 */
import cpp

/**
 * True if this function is declared in a header file.
 */
predicate isDeclaredInHeader(Function f) {
  exists(FunctionDeclarationEntry fde |
    fde.getFunction() = f and
    fde.getFile().getExtension().regexpMatch("h|hpp|hxx|H")
  )
}

/**
 * True if this function has external linkage (not static, not in anonymous namespace).
 */
predicate hasExternalLinkage(Function f) {
  not f.isStatic() and
  not f.getNamespace().isAnonymous()
}

/**
 * True if the function takes a pointer/array parameter (potential input buffer).
 */
predicate takesPointerParam(Function f) {
  exists(Parameter p |
    p = f.getAParameter() and
    (p.getType() instanceof PointerType or p.getType() instanceof ArrayType)
  )
}

/**
 * True if the function takes a size-like parameter (size_t, int, unsigned).
 */
predicate takesSizeParam(Function f) {
  exists(Parameter p |
    p = f.getAParameter() and
    p.getName().regexpMatch("(?i).*(size|len|length|count|num|n|sz).*")
  )
}

/**
 * True if function name suggests it processes input (parse, read, decode, load, etc.).
 */
predicate hasInputProcessingName(Function f) {
  f.getName().regexpMatch("(?i).*(parse|read|decode|load|deserialize|from|input|process|handle|recv|get|fetch|open|init|create|new|alloc).*")
}

/**
 * Get parameter info as "type name" string.
 */
string getParamInfo(Parameter p) {
  result = p.getType().toString() + " " + p.getName()
}

/**
 * Concatenate all parameters into a signature string.
 */
string getParamsSignature(Function f) {
  result = concat(int i, Parameter p |
    p = f.getParameter(i)
  |
    getParamInfo(p), ", " order by i
  )
}

/**
 * Compute an API score (higher = better fuzz target candidate).
 */
int apiScore(Function f) {
  result = 
    (if isDeclaredInHeader(f) then 3 else 0) +
    (if hasExternalLinkage(f) then 2 else 0) +
    (if takesPointerParam(f) then 2 else 0) +
    (if takesSizeParam(f) then 1 else 0) +
    (if hasInputProcessingName(f) then 2 else 0)
}

// String-returning wrappers for select
string inHeaderStr(Function f) { if isDeclaredInHeader(f) then result = "true" else result = "false" }
string externalLinkageStr(Function f) { if hasExternalLinkage(f) then result = "true" else result = "false" }
string takesPointerStr(Function f) { if takesPointerParam(f) then result = "true" else result = "false" }
string takesSizeStr(Function f) { if takesSizeParam(f) then result = "true" else result = "false" }
string inputProcessingStr(Function f) { if hasInputProcessingName(f) then result = "true" else result = "false" }

from Function f, int score
where
  f.getFile().fromSource() and
  not f.isCompilerGenerated() and
  f.hasDefinition() and
  score = apiScore(f) and
  // Only include functions with some API characteristics
  (isDeclaredInHeader(f) or hasExternalLinkage(f) or takesPointerParam(f) or hasInputProcessingName(f))
select
  f.getFile().getRelativePath() as file_path,
  f.getLocation().getStartLine() as line,
  f.getName() as name,
  f.getQualifiedName() as qualified_name,
  f.getType().toString() as return_type,
  f.getNumberOfParameters() as param_count,
  getParamsSignature(f) as parameters,
  inHeaderStr(f) as in_header,
  externalLinkageStr(f) as external_linkage,
  takesPointerStr(f) as takes_pointer,
  takesSizeStr(f) as takes_size,
  inputProcessingStr(f) as input_processing_name,
  score as api_score
order by score desc
