/**
 * @name Init and cleanup function pairs
 * @description Identify initialization and cleanup function pairs that should
 *              be called together in fuzz targets (e.g., init/cleanup, open/close,
 *              alloc/free, create/destroy).
 * @kind problem
 * @id futagassist/init-cleanup-pairs
 */
import cpp

/**
 * Match init/cleanup patterns.
 */
string getInitPattern() {
  result = "(?i)^(init|initialize|setup|open|create|alloc|new|start|begin|construct|make|build).*"
}

string getCleanupPattern() {
  result = "(?i)^(cleanup|clean|close|destroy|dealloc|free|delete|stop|end|finish|release|teardown|dispose|deinit|uninit|shutdown).*"
}

/**
 * True if function looks like an initializer.
 */
predicate isInitFunction(Function f) {
  f.getName().regexpMatch(getInitPattern()) or
  f.getName().regexpMatch("(?i).*_(init|open|create|alloc|new|start)$")
}

/**
 * True if function looks like a cleanup function.
 */
predicate isCleanupFunction(Function f) {
  f.getName().regexpMatch(getCleanupPattern()) or
  f.getName().regexpMatch("(?i).*_(cleanup|close|destroy|free|delete|end|release)$")
}

/**
 * Extract the base name (without init/cleanup suffix/prefix).
 */
string getBaseName(Function f) {
  // Remove common prefixes/suffixes to find matching pairs
  result = f.getName()
    .regexpReplaceAll("(?i)^(init_|initialize_|setup_|open_|create_|alloc_|new_|start_|begin_|construct_|make_|build_)", "")
    .regexpReplaceAll("(?i)^(cleanup_|clean_|close_|destroy_|dealloc_|free_|delete_|stop_|end_|finish_|release_|teardown_|dispose_|deinit_|uninit_|shutdown_)", "")
    .regexpReplaceAll("(?i)_(init|initialize|setup|open|create|alloc|new|start|begin|construct|make|build)$", "")
    .regexpReplaceAll("(?i)_(cleanup|clean|close|destroy|dealloc|free|delete|stop|end|finish|release|teardown|dispose|deinit|uninit|shutdown)$", "")
}

/**
 * Get parameter signature for matching.
 */
string getFirstParamType(Function f) {
  if f.getNumberOfParameters() > 0 
  then result = f.getParameter(0).getType().toString()
  else result = ""
}

from Function initFunc, Function cleanupFunc, string baseName
where
  initFunc.getFile().fromSource() and
  cleanupFunc.getFile().fromSource() and
  not initFunc.isCompilerGenerated() and
  not cleanupFunc.isCompilerGenerated() and
  isInitFunction(initFunc) and
  isCleanupFunction(cleanupFunc) and
  // Match by base name or first parameter type
  (
    (getBaseName(initFunc) = getBaseName(cleanupFunc) and getBaseName(initFunc) != "") or
    (getFirstParamType(initFunc) = getFirstParamType(cleanupFunc) and getFirstParamType(initFunc) != "" and
     initFunc.getQualifiedName().prefix(initFunc.getQualifiedName().length() - initFunc.getName().length()) =
     cleanupFunc.getQualifiedName().prefix(cleanupFunc.getQualifiedName().length() - cleanupFunc.getName().length()))
  ) and
  baseName = getBaseName(initFunc) and
  initFunc != cleanupFunc
select
  initFunc.getFile().getRelativePath() as init_file,
  initFunc.getLocation().getStartLine() as init_line,
  initFunc.getName() as init_name,
  initFunc.getQualifiedName() as init_qualified,
  cleanupFunc.getFile().getRelativePath() as cleanup_file,
  cleanupFunc.getLocation().getStartLine() as cleanup_line,
  cleanupFunc.getName() as cleanup_name,
  cleanupFunc.getQualifiedName() as cleanup_qualified,
  baseName as matched_base_name
