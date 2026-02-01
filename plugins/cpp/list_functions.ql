/**
 * List all functions in a C/C++ CodeQL database.
 * Output columns: file_path, line, name, signature (qualified name).
 * Used by the FutagAssist C++ language analyzer to build FunctionInfo.
 */
import cpp

from Function f
where f.getFile().fromSource()
select
  f.getFile().getRelativePath(),
  f.getLocation().getStartLine(),
  f.getName(),
  f.getQualifiedName()
