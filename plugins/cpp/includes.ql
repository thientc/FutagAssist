/**
 * @name Header includes per source file
 * @description Extract include directives for each source file to help generate
 *              complete fuzz harnesses with proper includes.
 * @kind problem
 * @id futagassist/includes
 */
import cpp

// String-returning wrapper for predicate
string isSystemStr(Include inc) { if inc.isSystemInclude() then result = "true" else result = "false" }

from Include inc, File sourceFile
where
  sourceFile = inc.getFile() and
  sourceFile.fromSource() and
  // Only direct includes (not transitive)
  exists(inc.getIncludedFile())
select
  sourceFile.getRelativePath() as source_file,
  inc.getIncludeText() as include_directive,
  inc.getIncludedFile().getRelativePath() as included_file,
  isSystemStr(inc) as is_system
order by source_file, inc.getLocation().getStartLine()
