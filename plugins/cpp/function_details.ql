/**
 * @name Function details for fuzz target generation
 * @description Extract detailed function information including return type, parameters,
 *              and qualifiers needed for generating fuzz harnesses.
 * @kind problem
 * @id futagassist/function-details
 */
import cpp

/**
 * Get a string representation of a parameter's type.
 */
string getParamTypeStr(Parameter p) {
  result = p.getType().toString()
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

// String-returning wrappers for select
string isStaticStr(Function f) { if f.hasSpecifier("static") then result = "true" else result = "false" }
string isInlineStr(Function f) { if f.isInline() then result = "true" else result = "false" }
string isVirtualStr(Function f) { if f.isVirtual() then result = "true" else result = "false" }

from Function f
where
  f.getFile().fromSource() and
  not f.isCompilerGenerated() and
  f.hasDefinition()
select
  f.getFile().getRelativePath() as file_path,
  f.getLocation().getStartLine() as line,
  f.getName() as name,
  f.getQualifiedName() as qualified_name,
  f.getType().toString() as return_type,
  f.getNumberOfParameters() as param_count,
  getParamsSignature(f) as parameters,
  isStaticStr(f) as is_static,
  isInlineStr(f) as is_inline,
  isVirtualStr(f) as is_virtual
