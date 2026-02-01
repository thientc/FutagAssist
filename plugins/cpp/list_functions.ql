/**
 * @name List all functions with details
 * @description List all functions in a C/C++ CodeQL database with detailed info.
 *              Output columns: file_path, line, name, qualified_name, return_type,
 *              param_count, parameters, is_public.
 *              Used by the FutagAssist C++ language analyzer to build FunctionInfo.
 * @kind problem
 * @id futagassist/list-functions
 */
import cpp

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
 * True if function is declared in a header (public API).
 */
predicate isPublicPred(Function f) {
  exists(FunctionDeclarationEntry fde |
    fde.getFunction() = f and
    fde.getFile().getExtension().regexpMatch("h|hpp|hxx|H")
  ) or
  (not f.isStatic() and not f.getNamespace().isAnonymous())
}

/**
 * Return "true" or "false" string for public status.
 */
string isPublic(Function f) {
  if isPublicPred(f) then result = "true" else result = "false"
}

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
  isPublic(f) as is_public
