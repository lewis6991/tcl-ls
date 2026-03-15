# Tcltest package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Define and run a named test case.
meta command tcltest::test {name description args}

# Load the tested commands into the current interpreter.
meta command tcltest::loadTestedCommands {}

# Create a temporary directory for a test.
meta command tcltest::makeDirectory {name ?directory?}

# Remove a temporary directory created by a test.
meta command tcltest::removeDirectory {name ?directory?}

# Create a temporary file for a test.
meta command tcltest::makeFile {contents name ?directory?}

# Remove a temporary file created by a test.
meta command tcltest::removeFile {name ?directory?}

# Display a file as part of test diagnostics.
meta command tcltest::viewFile {name ?directory?}

# Finish a test run and report accumulated results.
meta command tcltest::cleanupTests {?runningMultipleTests?}

# Run all matching test files.
meta command tcltest::runAllTests {?shell?}

# Read or update test harness options.
meta command tcltest::configure {args}

# Register a custom matcher for test results.
meta command tcltest::customMatch {mode command}

# Read or write a named test constraint.
meta command tcltest::testConstraint {constraint ?value?}

# Return or change the test output channel.
meta command tcltest::outputChannel {?channelId?}

# Return or change the test error channel.
meta command tcltest::errorChannel {?channelId?}

# Return or change the interpreter used for tests.
meta command tcltest::interpreter {?interp?}

# Read or change the internal debug level.
meta command tcltest::debug {?level?}

# Read or change the error output file.
meta command tcltest::errorFile {?filename?}

# Read or change whether constraints are limited.
meta command tcltest::limitConstraints {?boolean?}

# Read or change the load script file.
meta command tcltest::loadFile {?filename?}

# Read or change the script used to load tested commands.
meta command tcltest::loadScript {?script?}

# Read or change the list of matching test names.
meta command tcltest::match {?patternList?}

# Read or change the list of matching test files.
meta command tcltest::matchFiles {?patternList?}

# Read or change the list of matching test directories.
meta command tcltest::matchDirectories {?patternList?}

# Normalize a message before comparing test results.
meta command tcltest::normalizeMsg {message}

# Normalize a path in place for stable test comparisons.
meta command tcltest::normalizePath {pathVar}

# Read or change the output file for test runs.
meta command tcltest::outputFile {?filename?}

# Read or change core preservation behavior.
meta command tcltest::preserveCore {?level?}

# Read or change whether tests run in one process.
meta command tcltest::singleProcess {?boolean?}

# Read or change the list of skipped test names.
meta command tcltest::skip {?patternList?}

# Read or change the list of skipped directories.
meta command tcltest::skipDirectories {?patternList?}

# Read or change the list of skipped files.
meta command tcltest::skipFiles {?patternList?}

# Return or change the temporary directory for test files.
meta command tcltest::temporaryDirectory {?directory?}

# Return or change the active tests directory.
meta command tcltest::testsDirectory {?directory?}

# Read or change the verbose reporting level.
meta command tcltest::verbose {?level?}

# Return or change the working directory used by the harness.
meta command tcltest::workingDirectory {?dir?}

# Return the test files that match the current configuration.
meta command tcltest::getMatchingFiles {args}

# Return or change the main thread id used by the harness.
meta command tcltest::mainThread {?new?}

# Restore saved tcltest state for compatibility code.
meta command tcltest::restoreState {}

# Save tcltest state for compatibility code.
meta command tcltest::saveState {}

# Reap child threads created during tests.
meta command tcltest::threadReap {}

# Print an array using tcltest's output behavior.
meta command tcltest::parray {arrayName ?pattern?}
