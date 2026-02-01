/**
 * @name Parameter semantic roles for fuzz target generation
 * @description Classify each function parameter by semantic role (FILE_PATH, FILE_HANDLE, URL, etc.)
 *              based on parameter name and type. Used by the analyze stage to attach parameter_semantics
 *              to FunctionInfo; the generate stage consumes this to emit appropriate harness code.
 * @kind table
 * @id futagassist/parameter-semantics
 */
import cpp

predicate isFileHandleParam(Parameter p) {
  p.getType().toString().regexpMatch(".*FILE.*\\*.*") or
  (p.getType().toString() = "int" and p.getName().regexpMatch("(?i).*(fd|file|handle|stream|fp|fh).*"))
}

predicate isUserdataParam(Parameter p) {
  p.getType().toString().regexpMatch(".*void\\s*\\*.*") and
  p.getName().regexpMatch("(?i).*(userdata|user_data|ctx|context|opaque|cookie).*")
}

predicate isCallbackParam(Parameter p) {
  p.getName().regexpMatch("(?i).*(callback|cb|handler|_fn|_func|on_).*")
}

predicate isFilePathParam(Parameter p) {
  (p.getType().toString().regexpMatch(".*char.*\\*.*") or p.getType().toString().regexpMatch(".*string.*")) and
  p.getName().regexpMatch("(?i).*(filename|file_name|path|filepath|file_path|input_file|output_file|config_file|destname|src_file).*")
}

predicate isFilePathNameParam(Parameter p) {
  p.getName().regexpMatch("(?i).*_path.*") or p.getName() = "path"
}

predicate isConfigPathParam(Parameter p) {
  p.getName().regexpMatch("(?i).*(config_file|config_path|cfg_path|conf_path).*")
}

predicate isUrlParam(Parameter p) {
  p.getName().regexpMatch("(?i).*(url|uri|endpoint|link).*")
}

predicate isOutputBufferParam(Parameter p) {
  (p.getType() instanceof PointerType or p.getType() instanceof ArrayType) and
  p.getName().regexpMatch("(?i).*(out|output|_out|result|dest|dst).*")
}

predicate isInoutBufferParam(Parameter p) {
  (p.getType() instanceof PointerType or p.getType() instanceof ArrayType) and
  p.getName().regexpMatch("(?i).*(inout|io|buffer).*")
}

/**
 * Semantic role for a parameter. Priority order: FILE_HANDLE, USERDATA, CALLBACK, FILE_PATH, CONFIG_PATH, URL, OUTPUT_BUFFER, INOUT_BUFFER, UNKNOWN.
 */
string paramSemanticRole(Parameter p) {
  if isFileHandleParam(p) then result = "FILE_HANDLE"
  else if isUserdataParam(p) then result = "USERDATA"
  else if isCallbackParam(p) then result = "CALLBACK"
  else if isFilePathParam(p) or isFilePathNameParam(p) then result = "FILE_PATH"
  else if isConfigPathParam(p) then result = "CONFIG_PATH"
  else if isUrlParam(p) then result = "URL"
  else if isOutputBufferParam(p) then result = "OUTPUT_BUFFER"
  else if isInoutBufferParam(p) then result = "INOUT_BUFFER"
  else result = "UNKNOWN"
}

from Function f, int paramIndex, Parameter p
where
  f.getFile().fromSource() and
  not f.isCompilerGenerated() and
  f.hasDefinition() and
  p = f.getParameter(paramIndex)
select
  f.getFile().getRelativePath() as file_path,
  f.getLocation().getStartLine() as line,
  f.getName() as name,
  paramIndex as param_index,
  paramSemanticRole(p) as semantic_role
order by file_path, line, name, param_index
