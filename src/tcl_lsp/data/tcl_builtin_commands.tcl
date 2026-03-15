# Tcl builtin command metadata for tcl-ls.
# This file is parsed as Tcl source so builtin docs live in leading comment blocks.
# Duplicate command entries intentionally model different builtin overloads and variations.
# When sourced in a plain Tcl interpreter, define `meta` as a no-op so these
# declarations remain harmless.
# Descriptions are adapted from the Tcl 8.6 command manual.

if {[llength [info commands meta]] == 0} {
    proc meta {args} {}
}

# Declare metadata for Tcl language entities.
# tcl-ls treats this as structured documentation instead of executable
# behavior. The first argument names the metadata kind, followed by the entity
# name and a signature payload.
meta command meta {kind name signature}

# Execute a command after a time delay.
# Pause for the given number of milliseconds and then return. While the
# interpreter is waiting, the application does not respond to events.
meta command after {ms}

# Schedule a script to run after a time delay.
# Queue the concatenated script as a one-shot timer callback and return an
# identifier. The callback runs later at global level and can be cancelled
# with after cancel.
meta command after {ms script args}

# Schedule a script to run when the event loop is idle.
# Queue the concatenated script as a one-shot idle callback and return an
# identifier. The callback runs the next time the event loop is entered and no
# other events are ready.
meta command after {idle script args}

# Cancel a previously scheduled after handler.
# Cancel a pending timer or idle callback by handler id or by the script
# string that was scheduled. If the handler already ran or no match exists,
# this form has no effect.
meta command after {cancel idOrScript}

# Return information about scheduled after handlers.
# Without an id, return the identifiers for pending after handlers. With an
# id, return the associated script and whether the handler is an idle or timer
# callback.
meta command after {info {id {}}}

# Append to variable.
# Append all of the value arguments to the current value of variable varName.
# If varName does not exist, it is given a value equal to the concatenation of
# all the value arguments. The result of this command is the new value stored
# in variable varName.
meta command append {varName args}

# Apply an anonymous function.
# The command apply applies the function func to the arguments arg1 arg2...
# and returns the result.
meta command apply {lambdaExpr args}

# Manipulate array variables.
# This command performs one of several operations on the variable given by
# arrayName. Unless otherwise specified for individual commands below,
# arrayName must be the name of an existing array variable.
meta command array {subcommand args}

# Find executable files that match a command name.
# Determines whether there is an executable file or shell builtin by the name
# cmd. If so, it returns a list of arguments to be passed to exec to execute
# the executable file or shell builtin named by cmd. If not, it returns an
# empty string.
meta command auto_execok {name}

# Import exported namespace commands that match a pattern.
# Auto_import is invoked during namespace import to see if the imported
# commands specified by pattern reside in an autoloaded library. If so, the
# commands are loaded so that they will be available to the interpreter for
# creating the import links.
meta command auto_import {pattern}

# Load a command definition on first use.
# This command attempts to load the definition for a Tcl command named cmd. To
# do this, it searches an auto-load path, which is a list of one or more
# directories. The auto-load path is given by the global variable auto_path if
# it exists.
meta command auto_load {commandName}

# Generate namespace-qualified variants of a command name.
# Computes a list of fully qualified names for command. This list mirrors the
# path a standard Tcl interpreter follows for command lookups: first it looks
# for the command in the current namespace, and then in the global namespace.
meta command auto_qualify {commandName namespace}

# Insert and extract fields from binary strings.
# This command provides facilities for manipulating binary data. The
# subcommand binary format creates a binary string from normal Tcl values.
meta command binary {subcommand args}

# Abort looping command.
# This command is typically invoked inside the body of a looping command such
# as for or foreach or while. It returns a 3 ( TCL_BREAK ) result code, which
# causes a break exception to occur.
meta command break {}

# Evaluate script and trap exceptional returns.
# The catch command may be used to prevent errors from aborting command
# interpretation.
meta command catch {script {resultVarName {}} {optionsVarName {}}}

# Change working directory.
# Change the current working directory to dirName, or to the home directory
# (as specified in the HOME environment variable) if dirName is not given.
# Returns an empty string.
meta command cd {{dir ~}}

# Read, write and manipulate channels.
# This command provides several operations for reading from, writing to and
# otherwise manipulating open channels (such as have been created with the
# open and socket commands, or the default named channels stdin, stdout or
# stderr which correspond to the process's standard input, output and error
# streams respectively).
meta command chan {subcommand channelId args}

# Obtain and manipulate dates and times.
# The clock command performs several operations that obtain and manipulate
# values that represent times. The command supports several subcommands that
# determine what action is carried out by the command.
meta command clock {subcommand args}

# Close an open channel.
# Closes or half-closes the channel given by channelId.
meta command close {channelId}

# Join lists together.
# This command joins each of its arguments together with spaces after trimming
# leading and trailing white-space from each of them. If all of the arguments
# are lists, this has the same effect as concatenating them into a single
# list.
meta command concat {args}

# Skip to the next iteration of a loop.
# This command is typically invoked inside the body of a looping command such
# as for or foreach or while. It returns a 4 ( TCL_CONTINUE ) result code,
# which causes a continue exception to occur.
meta command continue {}

# Create and produce values from coroutines.
# The coroutine command creates a new coroutine context (with associated
# command) named name and executes that context by calling command, passing in
# the other remaining arguments without further interpretation.
meta command coroutine {name command args}

# Manipulate dictionaries.
# Performs one of several operations on dictionary values or variables
# containing dictionary values (see the DICTIONARY VALUES section below for a
# description), depending on option. The legal option s (which may be
# abbreviated) are:
meta command dict {subcommand args}

# Manipulate encodings.
meta command encoding {subcommand args}

# Check for end of file condition on channel.
# Returns 1 if an end of file condition occurred during the most recent input
# operation on channelId (such as gets ), 0 otherwise.
meta command eof {channelId}

# Generate an error.
# Returns a TCL_ERROR code, which causes command interpretation to be unwound.
# Message is a string that is returned to the application to indicate what
# went wrong.
meta command error {message {info {}} {code {}}}

# Evaluate a Tcl script.
# Eval takes one or more arguments, which together comprise a Tcl script
# containing one or more commands.
meta command eval {args}

# Invoke subprocesses.
# This command treats its arguments as the specification of one or more
# subprocesses to execute. The arguments take the form of a standard shell
# pipeline where each arg becomes one word of a command, and each distinct
# command becomes a subprocess.
meta command exec {args}

# End the application.
# Terminate the process, returning returnCode to the system as the exit
# status. If returnCode is not specified then it defaults to 0.
meta command exit {{returnCode 0}}

# Evaluate an expression.
# Concatenates arg s (adding separator spaces between them), evaluates the
# result as a Tcl expression, and returns the value. The operators permitted
# in Tcl expressions include a subset of the operators permitted in C
# expressions.
meta command expr {args}

# Test whether the last input operation exhausted all available input.
# The fblocked command returns 1 if the most recent input operation on
# channelId returned less information than requested because all available
# input was exhausted.
meta command fblocked {channelId}

# Set and get options on a channel.
# The fconfigure command sets and retrieves options for channels.
meta command fconfigure {channelId args}

# Copy data from one channel to another.
# The fcopy command copies data from one I/O channel, inchan to another I/O
# channel, outchan.
meta command fcopy {input output args}

# Manipulate file names and attributes.
# This command provides several operations on a file's name or attributes.
# Name is the name of a file; if it starts with a tilde, then tilde
# substitution is done before executing the command (see the manual entry for
# filename for details).
meta command file {subcommand args}

# Execute a script when a channel becomes readable or writable.
# This command is used to create file event handlers. A file event handler is
# a binding between a channel and a script, such that the script is evaluated
# whenever the channel becomes readable or writable.
meta command fileevent {channelId event script}

# Flush buffered output for a channel.
# Flushes any output that has been buffered for channelId.
meta command flush {channelId}

# 'For' loop.
# For is a looping command, similar in structure to the C for statement. The
# start, next, and body arguments must be Tcl command strings, and test is an
# expression string. The for command first invokes the Tcl interpreter to
# execute start.
meta command for {start test next body}

# Iterate over all elements in one or more lists.
# The foreach command implements a loop where the loop variable(s) take on
# values from one or more lists. In the simplest case there is one loop
# variable, varname, and one list, list, that is a list of values to assign to
# varname.
meta command foreach {varList list args}

# Format a string in the style of sprintf.
meta command format {formatString args}

# Read a line from a channel.
# This command reads the next line from channelId, returns everything in the
# line up to (but not including) the end-of-line character(s), and discards
# the end-of-line character(s).
meta command gets {channelId {varName {}}}

# Return names of files that match patterns.
# This command performs file name "globbing" in a fashion similar to the csh
# shell or bash shell. It returns a list of the files whose names match any of
# the pattern arguments.
meta command glob {args}

# Access global variables.
# This command has no effect unless executed in the context of a proc body.
meta command global {args}

# Manipulate the history list.
# The history command performs one of several operations related to
# recently-executed commands recorded in a history list. Each of these
# recorded commands is referred to as an "event".
meta command history {args}

# Execute scripts conditionally.
# The if command evaluates expr1 as an expression (in the same way that expr
# evaluates its argument).
meta command if {test body args}

# Increment the value of a variable.
# Increments the value stored in the variable whose name is varName. The value
# of the variable must be an integer. If increment is supplied then its value
# (which must be an integer) is added to the value of variable varName;
# otherwise 1 is added to varName.
meta command incr {varName {increment 1}}

# Return information about the state of the Tcl interpreter.
# This command provides information about various internals of the Tcl
# interpreter. The legal option s (which may be abbreviated) are:
meta command info {subcommand args}

# Create and manipulate Tcl interpreters.
# This command makes it possible to create one or more new Tcl interpreters
# that co-exist with the creating interpreter in the same application. The
# creating interpreter is called the parent and the new interpreter is called
# a child.
meta command interp {subcommand args}

# Create a string by joining together list elements.
# The list argument must be a valid Tcl list. This command returns the string
# formed by joining all of the elements of list together with joinString
# separating each adjacent pair of elements. The joinString argument defaults
# to a space character.
meta command join {list {joinString { }}}

# Append list elements onto a variable.
# This command treats the variable given by varName as a list and appends each
# of the value arguments to that list as a separate element, with spaces
# between elements. If varName does not exist, it is created as a list with
# elements given by the value arguments.
meta command lappend {varName args}

# Assign list elements to variables.
# This command treats the value list as a list and assigns successive elements
# from that list to the variables given by the varName arguments in order. If
# there are more variable names than list elements, the remaining variables
# are set to the empty string.
meta command lassign {list args}

# Retrieve an element from a list.
# The lindex command accepts a parameter, list, which it treats as a Tcl list.
# It also accepts zero or more indices into the list. The indices may be
# presented either consecutively on the command line, or grouped in a Tcl list
# and presented as a single argument.
meta command lindex {list args}

# Insert elements into a list.
# This command produces a new list from list by inserting all of the element
# arguments just before the index 'th element of list. Each element argument
# will become a separate element of the new list.
meta command linsert {list index args}

# Create a list.
# This command returns a list comprised of all the arg s, or an empty string
# if no arg s are specified.
meta command list {args}

# Count the number of elements in a list.
# Treats list as a list and returns a decimal string giving the number of
# elements in it.
meta command llength {list}

# Iterate over all elements in one or more lists and collect results.
# The lmap command implements a loop where the loop variable(s) take on values
# from one or more lists, and the loop returns a list of results collected
# from each iteration.
meta command lmap {varList list args}

# Load machine code and initialize new commands.
# This command loads binary code from a file into the application's address
# space and calls an initialization procedure in the library to incorporate it
# into an interpreter.
meta command load {fileName args}

# Return one or more adjacent elements from a list.
# List must be a valid Tcl list. This command will return a new list
# consisting of elements first through last, inclusive.
meta command lrange {list first last}

# Build a list by repeating elements.
# The lrepeat command creates a list of size count * number of elements by
# repeating count times the sequence of elements element.... count must be a
# non-negative integer, element can be any Tcl value. Note that lrepeat 1
# element...
meta command lrepeat {count args}

# Replace elements in a list with new elements.
# lreplace returns a new list formed by replacing zero or more elements of
# list with the element arguments. first and last are index values specifying
# the first and last elements of the range to replace.
meta command lreplace {list first last args}

# Reverse the order of a list.
# The lreverse command returns a list that has the same elements as its input
# list, list, except with the elements in the reverse order.
meta command lreverse {list}

# See if a list contains a particular element.
# This command searches the elements of list to see if one of them matches
# pattern.
meta command lsearch {args}

# Change an element in a list.
# The lset command accepts a parameter, varName, which it interprets as the
# name of a variable containing a Tcl list. It also accepts zero or more
# indices into the list.
meta command lset {varName args}

# Sort the elements of a list.
# This command sorts the elements of list, returning a new list in sorted
# order. The implementation of the lsort command uses the merge-sort algorithm
# which is a stable sort that has O(n log n) performance characteristics.
meta command lsort {args}

# Create and manipulate contexts for commands and variables.
# The namespace command lets you create, access, and destroy separate contexts
# for commands and variables. See the section WHAT IS A NAMESPACE? below for a
# brief overview of namespaces.
meta command namespace {subcommand args}

# Open a file-based or command pipeline channel.
# This command opens a file, serial port, or command pipeline and returns a
# channel identifier that may be used in future invocations of commands like
# read, puts, and close.
meta command open {fileName args}

# Facilities for package loading and version control.
# This command keeps a simple database of the packages available for use by
# the current interpreter and how to load them into the interpreter.
meta command package {subcommand args}

# Retrieve process identifiers.
# If the fileId argument is given then it should normally refer to a process
# pipeline created with the open command. In this case the pid command will
# return a list whose elements are the process identifiers of all the
# processes in the pipeline, in order.
meta command pid {{channelId {}}}

# Create a Tcl procedure.
# The proc command creates a new Tcl procedure named name, replacing any
# existing command or procedure there may have been by that name. Whenever the
# new command is invoked, the contents of body will be executed by the Tcl
# interpreter.
meta command proc {name argList body}

# Write to a channel.
# Writes the characters given by string to the channel given by channelId.
meta command puts {args}

# Return the absolute path of the current working directory.
# Returns the absolute path name of the current working directory.
meta command pwd {}

# Read from a channel.
# In the first form, the read command reads all of the data from channelId up
# to the end of the file. If the -nonewline switch is specified then the last
# character of the file is discarded if it is a newline.
meta command read {channelId {numChars {}}}

# Match a regular expression against a string.
# Determines whether the regular expression exp matches part or all of string
# and returns 1 if it does, 0 if it does not, unless -inline is specified (see
# below). (Regular expression matching is described in the re_syntax reference
# page.)
meta command regexp {args}

# Perform substitutions based on regular expression pattern matching.
# This command matches the regular expression exp against string, and either
# copies string to the variable whose name is given by varName or returns
# string if varName is not present.
meta command regsub {args}

# Rename or delete a command.
# Rename the command that used to be called oldName so that it is now called
# newName. If newName is an empty string then oldName is deleted. oldName and
# newName may include namespace qualifiers (names of containing namespaces).
meta command rename {oldName newName}

# Return from a procedure, or set return code of a script.
# In its simplest usage, the return command is used without options in the
# body of a procedure to immediately return control to the caller of the
# procedure.
meta command return {args}

# Parse string using conversion specifiers in the style of sscanf.
meta command scan {string format args}

# Change the access position for an open channel.
# Changes the current access position for channelId.
meta command seek {channelId offset {origin start}}

# Read and write variables.
# With one argument, return the current value of varName. With a value
# argument, assign and return the new value; names may refer to scalars, array
# elements, or namespace variables.
meta command set {varName args}

# Open a TCP network connection.
# This command opens a network socket and returns a channel identifier that
# may be used in future invocations of commands like read, puts and flush.
meta command socket {args}

# Evaluate a file or resource as a Tcl script.
# This command takes the contents of the specified file or resource and passes
# it to the Tcl interpreter as a text script. The return value from source is
# the return value of the last command executed in the script.
meta command source {fileName}

# Split a string into a proper Tcl list.
# Returns a list created by splitting string at each character that is in the
# splitChars argument. Each element of the result list will consist of the
# characters from string that lie between instances of the characters in
# splitChars.
meta command split {string {splitChars { }}}

# Manipulate strings.
# Performs one of several string operations, depending on option. The legal
# option s (which may be abbreviated) are:
meta command string {subcommand args}

# Perform backslash, command, and variable substitutions.
# This command performs variable substitutions, command substitutions, and
# backslash substitutions on its string argument and returns the
# fully-substituted result. The substitutions are performed in exactly the
# same way as for Tcl commands.
meta command subst {args}

# Evaluate one of several scripts, depending on a given value.
# The switch command matches its string argument against each of the pattern
# arguments in order.
meta command switch {args}

# Replace the current procedure with another command.
# The tailcall command replaces the currently executing procedure, lambda
# application, or method with another command. The command, which will have
# arg...
meta command tailcall {command args}

# Return current access position for an open channel.
# Returns an integer string giving the current access position in channelId.
# This value returned is a byte offset that can be passed to seek in order to
# set the channel to a particular position.
meta command tell {channelId}

# Generate a machine-readable error.
# This command causes the current evaluation to be unwound with an error.
meta command throw {type message}

# Time the execution of a script.
# This command will call the Tcl interpreter count times to evaluate script
# (or once if count is not specified). It will then return a string of the
# form
meta command time {script {count 1}}

# Calibrated performance measurements of script execution time.
# The timerate command does calibrated performance measurement of a Tcl
# command or script, script. The script should be written so that it can be
# executed multiple times during the performance measurement process.
meta command timerate {script {time 1000} {maxCount 0} {calibration 0}}

# Monitor variable accesses, command usages and command executions.
# This command causes Tcl commands to be executed whenever certain operations
# are invoked. The legal option s (which may be abbreviated) are:
meta command trace {subcommand args}

# Trap and process errors and exceptions.
# This command executes the script body and, depending on what the outcome of
# that script is (normal exit, error, or some other exceptional result), runs
# a handler script to deal with the case.
meta command try {body args}

# Handle attempts to use non-existent commands.
# This command is invoked by the Tcl interpreter whenever a script tries to
# invoke a command that does not exist. The default implementation of unknown
# is a library procedure defined when Tcl initializes an interpreter.
meta command unknown {args}

# Unload machine code.
# This command tries to unload shared libraries previously loaded with load
# from the application's address space.
meta command unload {fileName args}

# Delete variables.
# This command removes one or more variables. Each name is a variable name,
# specified in any of the ways acceptable to the set command. If a name refers
# to an element of an array then that element is removed without affecting the
# rest of the array.
meta command unset {args}

# Process pending events and idle callbacks.
# Enter the event loop until all pending events and idle callbacks have been
# processed. This is useful when long-running code still needs to keep the
# application responsive.
meta command update {}

# Process pending idle callbacks only.
# Run deferred idle work such as redraws and layout without processing new
# events or background errors. This is useful when you want display updates to
# happen immediately.
meta command update {idletasks}

# Execute a script in a different stack frame.
# All of the arg arguments are concatenated as if they had been passed to
# concat; the result is then evaluated in the variable context indicated by
# level. Uplevel returns the result of that evaluation.
meta command uplevel {args}

# Create link to variable in a different stack frame.
# This command arranges for one or more local variables in the current
# procedure to refer to variables in an enclosing procedure call or to global
# variables.
meta command upvar {args}

# Create and initialize a namespace variable.
# This command is normally used within a namespace eval command to create one
# or more variables within a namespace. Each variable name is initialized with
# value. The value for the last variable is optional.
meta command variable {args}

# Process events until a variable is written.
# This command enters the Tcl event loop to process events, blocking the
# application if no events are ready. It continues processing events until
# some event handler sets the value of the global variable varName.
meta command vwait {varName}

# Execute script repeatedly as long as a condition is met.
# The while command evaluates test as an expression (in the same way that expr
# evaluates its argument). The value of the expression must a proper boolean
# value; if it is a true value then body is executed by passing it to the Tcl
# interpreter.
meta command while {test body}

# Suspend a coroutine and produce a value.
# Suspend the current coroutine and return value to its caller; if no value is
# supplied, the empty string is used. Resuming the coroutine passes a single
# value back as the result of the yield call.
meta command yield {{value {}}}

# Suspend a coroutine and delegate to another command.
# Suspend the current coroutine and transfer control to another command, often
# another coroutine. When the coroutine is resumed, the yieldto call receives
# the list of arguments passed back to the coroutine command.
meta command yieldto {command args}

# Compression and decompression operations.
# The zlib command provides access to the compression and check-summing
# facilities of the Zlib library by Jean-loup Gailly and Mark Adler. It has
# the following subcommands.
meta command zlib {subcommand args}
