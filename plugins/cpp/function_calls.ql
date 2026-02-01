/**
 * @name Function call relationships
 * @description Extract caller-callee relationships to understand function usage patterns
 *              and construct realistic call sequences for fuzz targets.
 * @kind problem
 * @id futagassist/function-calls
 */
import cpp

from FunctionCall call, Function caller, Function callee
where
  caller = call.getEnclosingFunction() and
  callee = call.getTarget() and
  caller.getFile().fromSource() and
  callee.getFile().fromSource() and
  not caller.isCompilerGenerated() and
  not callee.isCompilerGenerated() and
  caller != callee  // Exclude recursive calls for simplicity
select
  caller.getFile().getRelativePath() as caller_file,
  caller.getLocation().getStartLine() as caller_line,
  caller.getName() as caller_name,
  caller.getQualifiedName() as caller_qualified,
  callee.getFile().getRelativePath() as callee_file,
  callee.getLocation().getStartLine() as callee_line,
  callee.getName() as callee_name,
  callee.getQualifiedName() as callee_qualified,
  call.getLocation().getStartLine() as call_site_line
