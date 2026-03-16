# Tcl builtin command metadata for tcl-ls.
# This file is parsed as Tcl source so builtin docs live in leading comment blocks.
# Duplicate command entries intentionally model different builtin overloads and variations.
# The metadata format itself is declared in meta/meta.tcl.
# Generated subcommand sections are maintained by scripts/generate_builtin_commands.py.
# Descriptions are adapted from the Tcl 8.6 command manual.
meta module Tcl

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
meta command append {varName args} {
    bind 1
}

# Apply an anonymous function.
# The command apply applies the function func to the arguments arg1 arg2...
# and returns the result.
meta command apply {lambdaExpr args}

# Manipulate array variables.
# This command performs one of several operations on the variable given by
# arrayName. Unless otherwise specified for individual commands below,
# arrayName must be the name of an existing array variable.
meta command array {subcommand args} {
    # @generated begin subcommands for array (Tcl 8.6)

    # Returns 1 if there are any more elements left to be processed in an
    # array search, 0 if all elements have already been returned.
    subcommand anymore {arrayName searchId}

    # This command terminates an array search and destroys all the state
    # associated with that search.
    subcommand donesearch {arrayName searchId}

    # Returns 1 if arrayName is an array variable, 0 if there is no variable
    # by that name or if it is a scalar variable.
    subcommand exists {arrayName}

    # Returns a list containing pairs of elements.
    subcommand get {arrayName ? pattern ?}

    # Returns a list containing the names of all of the elements in the array
    # that match pattern.
    subcommand names {arrayName ? mode ? ? pattern ?}

    # Returns the name of the next element in arrayName, or an empty string if
    # all elements of arrayName have already been returned in this search.
    subcommand nextelement {arrayName searchId}

    # Sets the values of one or more elements in arrayName. list must have a
    # form like that returned by array get, consisting of an even number of
    # elements.
    subcommand set {arrayName list}

    # Returns a decimal string giving the number of elements in the array.
    subcommand size {arrayName}

    # This command initializes an element-by-element search through the array
    # given by arrayName, such that invocations of the array nextelement
    # command will return the names of the individual elements in the array.
    subcommand startsearch {arrayName}

    # Returns statistics about the distribution of data within the hashtable
    # that represents the array.
    subcommand statistics {arrayName}

    # Unsets all of the elements in the array that match pattern (using the
    # matching rules of string match).
    subcommand unset {arrayName ? pattern ?}

    # @generated end subcommands for array
}
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
meta command binary {subcommand args} {
    # @generated begin subcommands for binary (Tcl 8.6)

    # Convert encoded text to binary data using the specified format.
    subcommand decode {format ?-option value ...? data} {

        # Decode base64 text into binary data.
        subcommand base64 {data ?-strict?}

        # Decode hexadecimal text into binary data.
        subcommand hex {data ?-strict?}

        # Decode uuencoded text into binary data.
        subcommand uuencode {data ?-strict?}
    }

    # Convert binary data to an encoded string using the specified format.
    subcommand encode {format ?-option value ...? data} {

        # Encode binary data as base64 text.
        subcommand base64 {data ?-maxlen length? ?-wrapchar character?}

        # Encode binary data as hexadecimal text.
        subcommand hex {data}

        # Encode binary data as uuencoded text.
        subcommand uuencode {data ?-maxlen length? ?-wrapchar character?}
    }

    # Generate a binary string from the values described by formatString.
    subcommand format {formatString ?arg arg ...?}

    # Parse fields from a binary string into Tcl variables.
    subcommand scan {string formatString ?varName varName ...?}

    # @generated end subcommands for binary
}
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
meta command chan {subcommand channelId args} {
    # @generated begin subcommands for chan (Tcl 8.6)

    # This tests whether the last input operation on the channel called
    # channelId failed because it would have otherwise caused the process to
    # block, and returns 1 if that was the case.
    subcommand blocked {channelId}

    # Close and destroy the channel called channelId.
    subcommand close {channelId ? direction ?}

    # Query or set the configuration options of the channel named channelId.
    subcommand configure {channelId ? optionName ? ? value ? ? optionName value ?...}

    # Copy data from the channel inputChan, which must have been opened for
    # reading, to the channel outputChan, which must have been opened for
    # writing.
    subcommand copy {inputChan outputChan ? -size size ? ? -command callback ?}

    # This subcommand creates a new script level channel using the command
    # prefix cmdPrefix as its handler.
    subcommand create {mode cmdPrefix}

    # Test whether the last input operation on the channel called channelId
    # failed because the end of the data stream was reached, returning 1 if
    # end-of-file was reached, and 0 otherwise.
    subcommand eof {channelId}

    # Arrange for the Tcl script script to be installed as a file event
    # handler to be called whenever the channel called channelId enters the
    # state described by event (which must be either readable or writable);
    # only one such handler may be installed per event per channel at a time.
    subcommand event {channelId event ? script ?}

    # Ensures that all pending output for the channel called channelId is
    # written.
    subcommand flush {channelId}

    # Reads the next line from the channel called channelId.
    subcommand gets {channelId ? varName ?}

    # Produces a list of all channel names.
    subcommand names {? pattern ?}

    # Depending on whether mode is input or output, returns the number of
    # bytes of input or output (respectively) currently buffered internally
    # for channelId (especially useful in a readable event callback to impose
    # application-specific limits on input line lengths to avoid a potential
    # denial-of-service attack where a hostile user crafts an extremely long
    # line that exceeds the available memory to buffer it).
    subcommand pending {mode channelId}

    # Creates a standalone pipe whose read- and write-side channels are
    # returned as a 2-element list, the first element being the read side and
    # the second the write side.
    subcommand pipe "{}"

    # Removes the topmost transformation from the channel channelId, if there
    # is any.
    subcommand pop {channelId}

    # This subcommand is used by command handlers specified with chan create.
    subcommand postevent {channelId eventSpec}

    # Adds a new transformation on top of the channel channelId.
    subcommand push {channelId cmdPrefix}

    # Writes string to the channel named channelId followed by a newline
    # character.
    subcommand puts {? -nonewline ? ? channelId ? string}

    # In the first form, the result will be the next numChars characters read
    # from the channel named channelId; if numChars is omitted, all characters
    # up to the point when the channel would signal a failure (whether an end-
    # of-file, blocked or other error condition) are read.
    subcommand read {channelId ? numChars ?}

    # In the first form, the result will be the next numChars characters read
    # from the channel named channelId; if numChars is omitted, all characters
    # up to the point when the channel would signal a failure (whether an end-
    # of-file, blocked or other error condition) are read.
    subcommand read {? -nonewline ? channelId}

    # In this form chan read blocks until numChars have been received from the
    # serial port.
    subcommand read {channelId numChars}

    # In this form chan read blocks until the reception of the end-of-file
    # character, see chan configure -eofchar.
    subcommand read {channelId}

    # Sets the current access position within the underlying data stream for
    # the channel named channelId to be offset bytes relative to origin.
    subcommand seek {channelId offset ? origin ?}

    # Returns a number giving the current access position within the
    # underlying data stream for the channel named channelId.
    subcommand tell {channelId}

    # Sets the byte length of the underlying data stream for the channel named
    # channelId to be length (or to the current byte offset within the
    # underlying data stream if length is omitted).
    subcommand truncate {channelId ? length ?}

    # @generated end subcommands for chan
}
# Obtain and manipulate dates and times.
# The clock command performs several operations that obtain and manipulate
# values that represent times. The command supports several subcommands that
# determine what action is carried out by the command.
meta command clock {subcommand args} {
    # @generated begin subcommands for clock (Tcl 8.6)

    # Adds a (possibly negative) offset to a time that is expressed as an
    # integer number of seconds.
    subcommand add {timeVal ? count unit... ? ? -option value ?}

    # If no -option argument is supplied, returns a high-resolution time value
    # as a system-dependent integer value.
    subcommand clicks {? -option ?}

    # Formats a time that is expressed as an integer number of seconds into a
    # format intended for consumption by users or external programs.
    subcommand format {timeVal ? -option value ...?}

    # Returns the current time as an integer number of microseconds.
    subcommand microseconds "{}"

    # Returns the current time as an integer number of milliseconds.
    subcommand milliseconds "{}"

    # Scans a time that is expressed as a character string and produces an
    # integer number of seconds.
    subcommand scan {inputString ? -option value ...?}

    # Returns the current time as an integer number of seconds.
    subcommand seconds "{}"

    # @generated end subcommands for clock
}
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
meta command dict {subcommand args} {
    # @generated begin subcommands for dict (Tcl 8.6)

    # This appends the given string (or strings) to the value that the given
    # key maps to in the dictionary value contained in the given variable,
    # writing the resulting dictionary value back to that variable.
    subcommand append {dictionaryVariable key ? string ... ?}

    # Return a new dictionary that contains each of the key/value mappings
    # listed as arguments (keys and values alternating, with each key being
    # followed by its associated value.)
    subcommand create {? key value ... ?}

    # This returns a boolean value indicating whether the given key (or path
    # of keys through a set of nested dictionaries) exists in the given
    # dictionary value.
    subcommand exists {dictionaryValue key ? key ... ?}

    # This takes a dictionary value and returns a new dictionary that contains
    # just those key/value pairs that match the specified filter type (which
    # may be abbreviated.)
    subcommand filter {dictionaryValue filterType arg ? arg ... ?} {

        # The key rule only matches those key/value pairs whose keys match any
        # of the given patterns (in the style of string match.)
        subcommand key {dictionaryValue ?globPattern ...?}

        # The script rule tests for matching by assigning the key to the
        # keyVariable and the value to the valueVariable, and then evaluating
        # the given script which should result in a boolean value (with the
        # key/value pair only being included in the result of the dict filter
        # when a true value is returned.)
        subcommand script "dictionaryValue {keyVariable valueVariable} script"

        # The value rule only matches those key/value pairs whose values match
        # any of the given patterns (in the style of string match.)
        subcommand value {dictionaryValue ?globPattern ...?}
    }

    # This command takes three arguments, the first a two-element list of
    # variable names (for the key and value respectively of each mapping in
    # the dictionary), the second the dictionary value to iterate across, and
    # the third a script to be evaluated for each mapping with the key and
    # value variables set appropriately (in the manner of foreach.)
    subcommand for "{ keyVariable valueVariable } dictionaryValue body"

    # Given a dictionary value (first argument) and a key (second argument),
    # this will retrieve the value for that key.
    subcommand get {dictionaryValue ? key ... ?}

    # This adds the given increment value (an integer that defaults to 1 if
    # not specified) to the value that the given key maps to in the dictionary
    # value contained in the given variable, writing the resulting dictionary
    # value back to that variable.
    subcommand incr {dictionaryVariable key ? increment ?}

    # This returns information (intended for display to people) about the
    # given dictionary though the format of this data is dependent on the
    # implementation of the dictionary.
    subcommand info {dictionaryValue}

    # Return a list of all keys in the given dictionary value.
    subcommand keys {dictionaryValue ? globPattern ?}

    # This appends the given items to the list value that the given key maps
    # to in the dictionary value contained in the given variable, writing the
    # resulting dictionary value back to that variable.
    subcommand lappend {dictionaryVariable key ? value ... ?}

    # This command applies a transformation to each element of a dictionary,
    # returning a new dictionary.
    subcommand map "{ keyVariable valueVariable } dictionaryValue body"

    # Return a dictionary that contains the contents of each of the
    # dictionaryValue arguments.
    subcommand merge {? dictionaryValue ... ?}

    # Return a new dictionary that is a copy of an old one passed in as first
    # argument except without mappings for each of the keys listed.
    subcommand remove {dictionaryValue ? key ... ?}

    # Return a new dictionary that is a copy of an old one passed in as first
    # argument except with some values different or some extra key/value pairs
    # added.
    subcommand replace {dictionaryValue ? key value ... ?}

    # This operation takes the name of a variable containing a dictionary
    # value and places an updated dictionary value in that variable containing
    # a mapping from the given key to the given value.
    subcommand set {dictionaryVariable key ? key ... ? value}

    # Return the number of key/value mappings in the given dictionary value.
    subcommand size {dictionaryValue}

    # This operation (the companion to dict set) takes the name of a variable
    # containing a dictionary value and places an updated dictionary value in
    # that variable that does not contain a mapping for the given key.
    subcommand unset {dictionaryVariable key ? key ... ?}

    # Execute the Tcl script in body with the value for each key (as found by
    # reading the dictionary value in dictionaryVariable) mapped to the
    # variable varName.
    subcommand update {dictionaryVariable key varName ? key varName ... ? body}

    # Return a list of all values in the given dictionary value.
    subcommand values {dictionaryValue ? globPattern ?}

    # Execute the Tcl script in body with the value for each key in
    # dictionaryVariable mapped (in a manner similarly to dict update) to a
    # variable with the same name.
    subcommand with {dictionaryVariable ? key ... ? body}

    # @generated end subcommands for dict
}
# Manipulate encodings.
meta command encoding {subcommand args} {
    # @generated begin subcommands for encoding (Tcl 8.6)

    # Convert data to Unicode from the specified encoding.
    subcommand convertfrom {? encoding ? data}

    # Convert string from Unicode to the specified encoding.
    subcommand convertto {? encoding ? string}

    # Tcl can load encoding data files from the file system that describe
    # additional encodings for it to work with.
    subcommand dirs {? directoryList ?}

    # Returns a list containing the names of all of the encodings that are
    # currently available.
    subcommand names "{}"

    # Set the system encoding to encoding.
    subcommand system {? encoding ?}

    # @generated end subcommands for encoding
}
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
meta command file {subcommand args} {
    # @generated begin subcommands for file (Tcl 8.6)

    # Returns a decimal string giving the time at which file name was last
    # accessed.
    subcommand atime {name ? time ?}

    # This subcommand returns or sets platform-specific values associated with
    # a file.
    subcommand attributes {name}

    # This subcommand returns or sets platform-specific values associated with
    # a file.
    subcommand attributes {name ? option ?}

    # This subcommand returns or sets platform-specific values associated with
    # a file.
    subcommand attributes {name ? option value option value... ?}

    # If pattern is not specified, returns a list of names of all registered
    # open channels in this interpreter.
    subcommand channels {? pattern ?}

    # The first form makes a copy of the file or directory source under the
    # pathname target.
    subcommand copy {? -force ? ? -- ? source target}

    # The first form makes a copy of the file or directory source under the
    # pathname target.
    subcommand copy {? -force ? ? -- ? source ? source ...? targetDir}

    # Removes the file or directory specified by each pathname argument.
    subcommand delete {? -force ? ? -- ? ? pathname ... ?}

    # Returns a name comprised of all of the path components in name excluding
    # the last element.
    subcommand dirname {name}

    # Returns 1 if file name is executable by the current user, 0 otherwise.
    subcommand executable {name}

    # Returns 1 if file name exists and the current user has search privileges
    # for the directories leading to it, 0 otherwise.
    subcommand exists {name}

    # Returns all of the characters in name after and including the last dot
    # in the last element of name.
    subcommand extension {name}

    # Returns 1 if file name is a directory, 0 otherwise.
    subcommand isdirectory {name}

    # Returns 1 if file name is a regular file, 0 otherwise.
    subcommand isfile {name}

    # Takes one or more file names and combines them, using the correct path
    # separator for the current platform.
    subcommand join {name ? name ... ?}

    # If only one argument is given, that argument is assumed to be linkName,
    # and this command returns the value of the link given by linkName (i.e.
    # the name of the file it points to).
    subcommand link {? -linktype ? linkName ? target ?}

    # Same as stat option (see below) except uses the lstat kernel call
    # instead of stat.
    subcommand lstat {name varName}

    # Creates each directory specified.
    subcommand mkdir {? dir ...?}

    # Returns a decimal string giving the time at which file name was last
    # modified.
    subcommand mtime {name ? time ?}

    # Returns the platform-specific name of the file.
    subcommand nativename {name}

    # Returns a unique normalized path representation for the file-system
    # object (file, directory, link, etc), whose string value can be used as a
    # unique identifier for it.
    subcommand normalize {name}

    # Returns 1 if file name is owned by the current user, 0 otherwise.
    subcommand owned {name}

    # Returns one of absolute, relative, volumerelative.
    subcommand pathtype {name}

    # Returns 1 if file name is readable by the current user, 0 otherwise.
    subcommand readable {name}

    # Returns the value of the symbolic link given by name (i.e. the name of
    # the file it points to).
    subcommand readlink {name}

    # The first form takes the file or directory specified by pathname source
    # and renames it to target, moving the file if the pathname target
    # specifies a name in a different directory.
    subcommand rename {? -force ? ? -- ? source target}

    # The first form takes the file or directory specified by pathname source
    # and renames it to target, moving the file if the pathname target
    # specifies a name in a different directory.
    subcommand rename {? -force ? ? -- ? source ? source ...? targetDir}

    # Returns all of the characters in name up to but not including the last
    # "." character in the last component of name.
    subcommand rootname {name}

    # If no argument is given, returns the character which is used to separate
    # path segments for native files on this platform.
    subcommand separator {? name ?}

    # Returns a decimal string giving the size of file name in bytes.
    subcommand size {name}

    # Returns a list whose elements are the path components in name.
    subcommand split {name}

    # Invokes the stat kernel call on name, and uses the variable given by
    # varName to hold information returned from the kernel call.
    subcommand stat {name varName}

    # Returns a list of one or two elements, the first of which is the name of
    # the filesystem to use for the file, and the second, if given, an
    # arbitrary string representing the filesystem-specific nature or type of
    # the location within that filesystem.
    subcommand system {name}

    # Returns all of the characters in the last filesystem component of name.
    subcommand tail {name}

    # Creates a temporary file and returns a read-write channel opened on that
    # file.
    subcommand tempfile {? nameVar ? ? template ?}

    # Returns a string giving the type of file name, which will be one of
    # file, directory, characterSpecial, blockSpecial, fifo, link, or socket.
    subcommand type {name}

    # Returns the absolute paths to the volumes mounted on the system, as a
    # proper Tcl list.
    subcommand volumes "{}"

    # Returns 1 if file name is writable by the current user, 0 otherwise.
    subcommand writable {name}

    # @generated end subcommands for file
}
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
meta command gets {channelId {varName {}}} {
    bind 2
}

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
meta command incr {varName {increment 1}} {
    bind 1
}

# Return information about the state of the Tcl interpreter.
# This command provides information about various internals of the Tcl
# interpreter. The legal option s (which may be abbreviated) are:
meta command info {subcommand args} {
    # @generated begin subcommands for info (Tcl 8.6)

    # Returns a list containing the names of the arguments to procedure
    # procname, in order.
    subcommand args {procname}

    # Returns the body of procedure procname.
    subcommand body {procname}

    # Returns information about the class, class.
    subcommand class {subcommand class ? arg ...} {

        # Returns a description of the method implementations that are used to
        # provide a stereotypical instance of class 's implementation of
        # method (stereotypical instances being objects instantiated by a
        # class without having any object-specific definitions added).
        subcommand call {class method}

        # This subcommand returns a description of the definition of the
        # constructor of class class.
        subcommand constructor {class}

        # This subcommand returns a description of the definition of the
        # method named method of class class.
        subcommand definition {class method}

        # This subcommand returns the body of the destructor of class class.
        subcommand destructor {class}

        # This subcommand returns the list of filter methods set on the class.
        subcommand filters {class}

        # This subcommand returns the argument list for the method forwarding
        # called method that is set on the class called class.
        subcommand forward {class method}

        # This subcommand returns a list of instances of class class.
        subcommand instances {class ? pattern ?}

        # This subcommand returns a list of all public (i.e. exported) methods
        # of the class called class.
        subcommand methods {class ? options... ?}

        # This subcommand returns a description of the type of implementation
        # used for the method named method of class class.
        subcommand methodtype {class method}

        # This subcommand returns a list of all classes that have been mixed
        # into the class named class.
        subcommand mixins {class}

        # This subcommand returns a list of direct subclasses of class class.
        subcommand subclasses {class ? pattern ?}

        # This subcommand returns a list of direct superclasses of class class
        # in inheritance precedence order.
        subcommand superclasses {class}

        # This subcommand returns a list of all variables that have been
        # declared for the class named class (i.e. that are automatically
        # present in the class's methods, constructor and destructor).
        subcommand variables {class}
    }

    # Returns a count of the total number of commands that have been invoked
    # in this interpreter.
    subcommand cmdcount "{}"

    # If pattern is not specified, returns a list of names of all the Tcl
    # commands visible (i.e. executable without using a qualified name) to the
    # current namespace, including both the built-in commands written in C and
    # the command procedures defined using the proc command.
    subcommand commands {? pattern ?}

    # Returns 1 if command is a complete Tcl command in the sense of having no
    # unclosed quotes, braces, brackets or array element names.
    subcommand complete {command}

    # Returns the name of the currently executing coroutine, or the empty
    # string if either no coroutine is currently executing, or the current
    # coroutine has been deleted (but has not yet returned or yielded since
    # deletion).
    subcommand coroutine "{}"

    # Procname must be the name of a Tcl command procedure and arg must be the
    # name of an argument to that procedure.
    subcommand default {procname arg varname}

    # Returns, in a form that is programmatically easy to parse, the function
    # names and arguments at each level from the call stack of the last error
    # in the given interp, or in the current one if not specified.
    subcommand errorstack {? interp ?}

    # Returns 1 if the variable named varName exists in the current context
    # (either as a global or local variable) and has been defined by being
    # given a value, returns 0 otherwise.
    subcommand exists {varName}

    # This command provides access to all frames on the stack, even those
    # hidden from info level.
    subcommand frame {? number ?}

    # If pattern is not specified, returns a list of all the math functions
    # currently defined.
    subcommand functions {? pattern ?}

    # If pattern is not specified, returns a list of all the names of
    # currently-defined global variables.
    subcommand globals {? pattern ?}

    # Returns the name of the computer on which this invocation is being
    # executed.
    subcommand hostname "{}"

    # If number is not specified, this command returns a number giving the
    # stack level of the invoking procedure, or 0 if the command is invoked at
    # top-level.
    subcommand level {? number ?}

    # Returns the name of the library directory in which standard Tcl scripts
    # are stored.
    subcommand library "{}"

    # Returns a list describing all of the packages that have been loaded into
    # interp with the load command.
    subcommand loaded {? interp ?}

    # If pattern is not specified, returns a list of all the names of
    # currently-defined local variables, including arguments to the current
    # procedure, if any.
    subcommand locals {? pattern ?}

    # Returns the full path name of the binary file from which the application
    # was invoked.
    subcommand nameofexecutable "{}"

    # Returns information about the object, object.
    subcommand object {subcommand object ? arg ...} {

        # Returns a description of the method implementations that are used to
        # provide object 's implementation of method.
        subcommand call {object method}

        # If className is unspecified, this subcommand returns class of the
        # object object.
        subcommand class {object ? className ?}

        # This subcommand returns a description of the definition of the
        # method named method of object object.
        subcommand definition {object method}

        # This subcommand returns the list of filter methods set on the
        # object.
        subcommand filters {object}

        # This subcommand returns the argument list for the method forwarding
        # called method that is set on the object called object.
        subcommand forward {object method}

        # This subcommand tests whether an object belongs to a particular
        # category, returning a boolean value that indicates whether the
        # object argument meets the criteria for the category.
        subcommand isa {category object ? arg ?} {

            # This returns whether object is a class (i.e. an instance of
            # oo::class or one of its subclasses).
            subcommand class {object}

            # This returns whether object is a class that can manufacture
            # classes (i.e. is oo::class or a subclass of it).
            subcommand metaclass {object}

            # This returns whether class is directly mixed into object.
            subcommand mixin {object class}

            # This returns whether object really is an object.
            subcommand object {object}

            # This returns whether class is the type of object (i.e. whether
            # object is an instance of class or one of its subclasses, whether
            # direct or indirect).
            subcommand typeof {object class}
        }

        # This subcommand returns a list of all public (i.e. exported) methods
        # of the object called object.
        subcommand methods {object ? option... ?}

        # This subcommand returns a description of the type of implementation
        # used for the method named method of object object.
        subcommand methodtype {object method}

        # This subcommand returns a list of all classes that have been mixed
        # into the object named object.
        subcommand mixins {object}

        # This subcommand returns the name of the internal namespace of the
        # object named object.
        subcommand namespace {object}

        # This subcommand returns a list of all variables that have been
        # declared for the object named object (i.e. that are automatically
        # present in the object's methods).
        subcommand variables {object}

        # This subcommand returns a list of all variables in the private
        # namespace of the object named object.
        subcommand vars {object ? pattern ?}
    }

    # Returns the value of the global variable tcl_patchLevel, which holds the
    # exact version of the Tcl library by default.
    subcommand patchlevel "{}"

    # If pattern is not specified, returns a list of all the names of Tcl
    # command procedures in the current namespace.
    subcommand procs {? pattern ?}

    # If a Tcl script file is currently being evaluated (i.e. there is a call
    # to Tcl_EvalFile active or there is an active invocation of the source
    # command), then this command returns the name of the innermost file being
    # processed.
    subcommand script {? filename ?}

    # Returns the extension used on this platform for the names of files
    # containing shared libraries (for example,.so under Solaris).
    subcommand sharedlibextension "{}"

    # Returns the value of the global variable tcl_version, which holds the
    # major and minor version of the Tcl library by default.
    subcommand tclversion "{}"

    # If pattern is not specified, returns a list of all the names of
    # currently-visible variables.
    subcommand vars {? pattern ?}

    # @generated end subcommands for info
}
# Create and manipulate Tcl interpreters.
# This command makes it possible to create one or more new Tcl interpreters
# that co-exist with the creating interpreter in the same application. The
# creating interpreter is called the parent and the new interpreter is called
# a child.
meta command interp {subcommand args} {
    # @generated begin subcommands for interp (Tcl 8.6)

    # Returns a Tcl list whose elements are the targetCmd and arg s associated
    # with the alias represented by srcToken (this is the value returned when
    # the alias was created; it is possible that the name of the source
    # command in the child is different from srcToken).
    subcommand alias {srcPath srcToken}

    # Deletes the alias for srcToken in the child interpreter identified by
    # srcPath. srcToken refers to the value returned when the alias was
    # created; if the source command has been renamed, the renamed command
    # will be deleted.
    subcommand alias "srcPath srcToken {}"

    # This command creates an alias between one child and another (see the
    # alias child command below for creating aliases between a child and its
    # parent).
    subcommand alias {srcPath srcCmd targetPath targetCmd ? arg arg ... ?}

    # This command returns a Tcl list of the tokens of all the source commands
    # for aliases defined in the interpreter identified by path.
    subcommand aliases {? path ?}

    # This command either gets or sets the current background exception
    # handler for the interpreter identified by path.
    subcommand bgerror {path ? cmdPrefix ?}

    # Cancels the script being evaluated in the interpreter identified by
    # path.
    subcommand cancel {? -unwind ? ? -- ? ? path ? ? result ?}

    # Creates a child interpreter identified by path and a new command, called
    # a child command.
    subcommand create {? -safe ? ? -- ? ? path ?}

    # Controls whether frame-level stack information is captured in the child
    # interpreter identified by path.
    subcommand debug {path ? -frame ? bool ??}

    # Deletes zero or more interpreters given by the optional path arguments,
    # and for each interpreter, it also deletes its children.
    subcommand delete {? path ...?}

    # This command concatenates all of the arg arguments in the same fashion
    # as the concat command, then evaluates the resulting string as a Tcl
    # script in the child interpreter identified by path.
    subcommand eval {path arg ? arg ... ?}

    # Returns 1 if a child interpreter by the specified path exists in this
    # parent, 0 otherwise.
    subcommand exists {path}

    # Makes the hidden command hiddenName exposed, eventually bringing it back
    # under a new exposedCmdName name (this name is currently accepted only if
    # it is a valid global name space name without any::), in the interpreter
    # denoted by path.
    subcommand expose {path hiddenName ? exposedCmdName ?}

    # Makes the exposed command exposedCmdName hidden, renaming it to the
    # hidden command hiddenCmdName, or keeping the same name if hiddenCmdName
    # is not given, in the interpreter denoted by path.
    subcommand hide {path exposedCmdName ? hiddenCmdName ?}

    # Returns a list of the names of all hidden commands in the interpreter
    # identified by path.
    subcommand hidden {path}

    # Invokes the hidden command hiddenCmdName with the arguments supplied in
    # the interpreter denoted by path.
    subcommand invokehidden {path ? -option ... ? hiddenCmdName ? arg ... ?}

    # Returns 1 if the interpreter identified by the specified path is safe, 0
    # otherwise.
    subcommand issafe {? path ?}

    # Sets up, manipulates and queries the configuration of the resource limit
    # limitType for the interpreter denoted by path.
    subcommand limit {path limitType ? -option ? ? value ... ?}

    # Marks the interpreter identified by path as trusted.
    subcommand marktrusted {path}

    # Returns the maximum allowable nesting depth for the interpreter
    # specified by path.
    subcommand recursionlimit {path ? newlimit ?}

    # Causes the IO channel identified by channelId to become shared between
    # the interpreter identified by srcPath and the interpreter identified by
    # destPath.
    subcommand share {srcPath channelId destPath}

    # Returns a Tcl list of the names of all the child interpreters associated
    # with the interpreter identified by path.
    subcommand slaves {? path ?}

    # Alias for interp slaves.
    subcommand children {? path ?}

    # Returns a Tcl list describing the target interpreter for an alias.
    subcommand target {path alias}

    # Causes the IO channel identified by channelId to become available in the
    # interpreter identified by destPath and unavailable in the interpreter
    # identified by srcPath.
    subcommand transfer {srcPath channelId destPath}

    # @generated end subcommands for interp
}
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
meta command lappend {varName args} {
    bind 1
}

# Assign list elements to variables.
# This command treats the value list as a list and assigns successive elements
# from that list to the variables given by the varName arguments in order. If
# there are more variable names than list elements, the remaining variables
# are set to the empty string.
meta command lassign {list args} {
    bind 2..
}

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
meta command namespace {subcommand args} {
    # @generated begin subcommands for namespace (Tcl 8.6)

    # Returns a list of all child namespaces that belong to the namespace
    # namespace.
    subcommand children {? namespace ? ? pattern ?}

    # Captures the current namespace context for later execution of the script
    # script.
    subcommand code {script}

    # Returns the fully-qualified name for the current namespace.
    subcommand current "{}"

    # Each namespace namespace is deleted and all variables, procedures, and
    # child namespaces contained in the namespace are deleted.
    subcommand delete {? namespace namespace ... ?}

    # Creates and manipulates a command that is formed out of an ensemble of
    # subcommands.
    subcommand ensemble {subcommand ? arg ... ?} {

        # Creates a new ensemble command linked to the current namespace,
        # returning the fully qualified name of the command created.
        subcommand create {? option value ... ?}

        # Retrieves the value of an option associated with the ensemble
        # command named command, or updates some options associated with that
        # ensemble command.
        subcommand configure {command ? option ? ? value ... ?}

        # Returns a boolean value that describes whether the command command
        # exists and is an ensemble command.
        subcommand exists {command}
    }

    # Activates a namespace called namespace and evaluates some code in that
    # context.
    subcommand eval {namespace arg ? arg ... ?}

    # Returns 1 if namespace is a valid namespace in the current context,
    # returns 0 otherwise.
    subcommand exists {namespace}

    # Specifies which commands are exported from a namespace.
    subcommand export {? -clear ? ? pattern pattern ... ?}

    # Removes previously imported commands from a namespace.
    subcommand forget {? pattern pattern ... ?}

    # Imports commands into a namespace, or queries the set of imported
    # commands in a namespace.
    subcommand import {? -force ? ? pattern pattern ... ?}

    # Executes a script in the context of the specified namespace.
    subcommand inscope {namespace script ? arg ... ?}

    # Returns the fully-qualified name of the original command to which the
    # imported command command refers.
    subcommand origin {command}

    # Returns the fully-qualified name of the parent namespace for namespace
    # namespace.
    subcommand parent {? namespace ?}

    # Returns the command resolution path of the current namespace.
    subcommand path {? namespaceList ?}

    # Returns any leading namespace qualifiers for string.
    subcommand qualifiers {string}

    # Returns the simple name at the end of a qualified string.
    subcommand tail {string}

    # This command arranges for zero or more local variables in the current
    # procedure to refer to variables in namespace.
    subcommand upvar {namespace ? otherVar myVar ...?}

    # Sets or returns the unknown command handler for the current namespace.
    subcommand unknown {? script ?}

    # Looks up name as either a command or variable and returns its fully-
    # qualified name.
    subcommand which {? -command ? ? -variable ? name}

    # @generated end subcommands for namespace
}
# Open a file-based or command pipeline channel.
# This command opens a file, serial port, or command pipeline and returns a
# channel identifier that may be used in future invocations of commands like
# read, puts, and close.
meta command open {fileName args}

# Facilities for package loading and version control.
# This command keeps a simple database of the packages available for use by
# the current interpreter and how to load them into the interpreter.
meta command package {subcommand args} {
    # @generated begin subcommands for package (Tcl 8.6)

    # Removes all information about each specified package from this
    # interpreter, including information provided by both package ifneeded and
    # package provide.
    subcommand forget {? package package ... ?}

    # This command typically appears only in system configuration scripts to
    # set up the package database.
    subcommand ifneeded {package version ? script ?}

    # Returns a list of the names of all packages in the interpreter for which
    # a version has been provided (via package provide) or for which a package
    # ifneeded script is available.
    subcommand names "{}"

    # This command is equivalent to package require except that it does not
    # try and load the package if it is not already loaded.
    subcommand present {? -exact ? package ? requirement... ?}

    # This command is invoked to indicate that version version of package
    # package is now present in the interpreter.
    subcommand provide {package ? version ?}

    # This command is typically invoked by Tcl code that wishes to use a
    # particular version of a particular package.
    subcommand require {package ? requirement... ?}

    # This form of the command is used when only the given version of package
    # is acceptable to the caller.
    subcommand require {-exact package version}

    # This command supplies a "last resort" command to invoke during package
    # require if no suitable version of a package can be found in the package
    # ifneeded database.
    subcommand unknown {? command ?}

    # Compares the two version numbers given by version1 and version2.
    subcommand vcompare {version1 version2}

    # Returns a list of all the version numbers of package for which
    # information has been provided by package ifneeded commands.
    subcommand versions {package}

    # Returns 1 if the version satisfies at least one of the given
    # requirements, and 0 otherwise. requirements are defined in the
    # REQUIREMENT section below.
    subcommand vsatisfies {version requirement...}

    # Get or set whether package selection prefers the latest or stable
    # version.
    subcommand prefer {? latest | stable ?}

    # @generated end subcommands for package
}
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
meta command regexp {args} {
    option -all
    option -about
    option -expanded
    option -indices
    option -inline
    option -line
    option -lineanchor
    option -linestop
    option -nocase
    option -start value
    option -- stop
    bind after-options 3..
}

# Perform substitutions based on regular expression pattern matching.
# This command matches the regular expression exp against string, and either
# copies string to the variable whose name is given by varName or returns
# string if varName is not present.
meta command regsub {args} {
    option -all
    option -expanded
    option -line
    option -lineanchor
    option -linestop
    option -nocase
    option -start value
    option -- stop
    bind after-options 4
}

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
meta command scan {string format args} {
    bind 3..
}

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
meta command string {subcommand args} {
    # @generated begin subcommands for string (Tcl 8.6)

    # Concatenate the given string s just like placing them directly next to
    # each other and return the resulting compound string.
    subcommand cat {? string1 ? ? string2... ?}

    # Perform a character-by-character comparison of strings string1 and
    # string2.
    subcommand compare {? -nocase ? ? -length length ? string1 string2}

    # Perform a character-by-character comparison of strings string1 and
    # string2.
    subcommand equal {? -nocase ? ? -length length ? string1 string2}

    # Search haystackString for a sequence of characters that exactly match
    # the characters in needleString.
    subcommand first {needleString haystackString ? startIndex ?}

    # Returns the charIndex 'th character of the string argument.
    subcommand index {string charIndex}

    # Returns 1 if string is a valid member of the specified character class,
    # otherwise returns 0.
    subcommand is {class ? -strict ? ? -failindex varname ? string}

    # Search haystackString for a sequence of characters that exactly match
    # the characters in needleString.
    subcommand last {needleString haystackString ? lastIndex ?}

    # Returns a decimal string giving the number of characters in string.
    subcommand length {string}

    # Replaces substrings in string based on the key-value pairs in mapping.
    # mapping is a list of key value key value... as in the form returned by
    # array get.
    subcommand map {? -nocase ? mapping string}

    # See if pattern matches string; return 1 if it does, 0 if it does not.
    subcommand match {? -nocase ? pattern string}

    # Returns a range of consecutive characters from string, starting with the
    # character whose index is first and ending with the character whose index
    # is last (using the forms described in STRING INDICES).
    subcommand range {string first last}

    # Returns a string consisting of string concatenated with itself count
    # times.
    subcommand repeat {string count}

    # Removes a range of consecutive characters from string, starting with the
    # character whose index is first and ending with the character whose index
    # is last (using the forms described in STRING INDICES).
    subcommand replace {string first last ? newstring ?}

    # Returns a string that is the same length as string but with its
    # characters in the reverse order.
    subcommand reverse {string}

    # Returns a value equal to string except that all upper (or title) case
    # letters have been converted to lower case.
    subcommand tolower {string ? first ? ? last ?}

    # Returns a value equal to string except that the first character in
    # string is converted to its Unicode title case variant (or upper case if
    # there is no title case variant) and the rest of the string is converted
    # to lower case.
    subcommand totitle {string ? first ? ? last ?}

    # Returns a value equal to string except that all lower (or title) case
    # letters have been converted to upper case.
    subcommand toupper {string ? first ? ? last ?}

    # Returns a value equal to string except that any leading or trailing
    # characters present in the string given by chars are removed.
    subcommand trim {string ? chars ?}

    # Returns a value equal to string except that any leading characters
    # present in the string given by chars are removed.
    subcommand trimleft {string ? chars ?}

    # Returns a value equal to string except that any trailing characters
    # present in the string given by chars are removed.
    subcommand trimright {string ? chars ?}

    # Returns a decimal string giving the number of bytes used to represent
    # string in memory when encoded as Tcl's internal modified UTF-8; Tcl may
    # use other encodings for string as well, and does not guarantee to only
    # use a single encoding for a particular string.
    subcommand bytelength {string}

    # Returns the index of the character just after the last one in the word
    # containing character charIndex of string. charIndex may be specified
    # using the forms in STRING INDICES.
    subcommand wordend {string charIndex}

    # Returns the index of the first character in the word containing
    # character charIndex of string. charIndex may be specified using the
    # forms in STRING INDICES.
    subcommand wordstart {string charIndex}

    # @generated end subcommands for string
}
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
meta command trace {subcommand args} {
    # @generated begin subcommands for trace (Tcl 8.6)

    # Where type is command, execution, or variable.
    subcommand add {type name ops ?args?} {

        # Arrange for commandPrefix to be executed (with additional arguments)
        # whenever command name is modified in one of the ways given by the
        # list ops.
        subcommand command {name ops commandPrefix}

        # Arrange for commandPrefix to be executed (with additional arguments)
        # whenever command name is executed, with traces occurring at the
        # points indicated by the list ops.
        subcommand execution {name ops commandPrefix}

        # Arrange for commandPrefix to be executed whenever variable name is
        # accessed in one of the ways given by the list ops.
        subcommand variable {name ops commandPrefix}
    }

    # Where type is either command, execution or variable.
    subcommand remove {type name opList commandPrefix} {

        # If there is a trace set on command name with the operations and
        # command given by opList and commandPrefix, then the trace is
        # removed, so that commandPrefix will never again be invoked.
        subcommand command {name opList commandPrefix}

        # If there is a trace set on command name with the operations and
        # command given by opList and commandPrefix, then the trace is
        # removed, so that commandPrefix will never again be invoked.
        subcommand execution {name opList commandPrefix}

        # If there is a trace set on variable name with the operations and
        # command given by opList and commandPrefix, then the trace is
        # removed, so that commandPrefix will never again be invoked.
        subcommand variable {name opList commandPrefix}
    }

    # Where type is either command, execution or variable.
    subcommand info {type name} {

        # Returns a list containing one element for each trace currently set
        # on command name.
        subcommand command {name}

        # Returns a list containing one element for each trace currently set
        # on command name.
        subcommand execution {name}

        # Returns a list containing one element for each trace currently set
        # on variable name.
        subcommand variable {name}
    }

    # This is equivalent to trace add variable name ops command.
    subcommand variable {name ops command}

    # This is equivalent to trace remove variable name ops command
    subcommand vdelete {name ops command}

    # This is equivalent to trace info variable name
    subcommand vinfo {name}

    # @generated end subcommands for trace
}
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
meta command zlib {subcommand args} {
    # @generated begin subcommands for zlib (Tcl 8.6)

    # Returns the zlib-format compressed binary data of the binary string in
    # string.
    subcommand compress {string ? level ?}

    # Returns the uncompressed version of the raw compressed binary data in
    # string.
    subcommand decompress {string ? bufferSize ?}

    # Returns the raw compressed binary data of the binary string in string.
    subcommand deflate {string ? level ?}

    # Return the uncompressed contents of binary string string, which must
    # have been in gzip format.
    subcommand gunzip {string ? -headerVar varName ?}

    # Return the compressed contents of binary string string in gzip format.
    subcommand gzip {string ? -level level ? ? -header dict ?}

    # Returns the uncompressed version of the raw compressed binary data in
    # string.
    subcommand inflate {string ? bufferSize ?}

    # Pushes a compressing or decompressing transformation onto the channel
    # channel.
    subcommand push {mode channel ? options ... ?}

    # Creates a streaming compression or decompression command based on the
    # mode, and return the name of the command.
    subcommand stream {mode ? options ?} {

        # The stream will be a compressing stream that produces zlib-format
        # output, using compression level level (if specified) which will be
        # an integer from 0 to 9, and the compression dictionary bindata (if
        # specified).
        subcommand compress {? -dictionary bindata ? ? -level level ?}

        # The stream will be a decompressing stream that takes zlib-format
        # input and produces uncompressed output.
        subcommand decompress {? -dictionary bindata ?}

        # The stream will be a compressing stream that produces raw output,
        # using compression level level (if specified) which will be an
        # integer from 0 to 9, and the compression dictionary bindata (if
        # specified).
        subcommand deflate {? -dictionary bindata ? ? -level level ?}

        # The stream will be a decompressing stream that takes gzip-format
        # input and produces uncompressed output.
        subcommand gunzip "{}"

        # The stream will be a compressing stream that produces gzip-format
        # output, using compression level level (if specified) which will be
        # an integer from 0 to 9, and the header descriptor dictionary header
        # (if specified; for keys see zlib gzip).
        subcommand gzip {? -header header ? ? -level level ?}

        # The stream will be a decompressing stream that takes raw compressed
        # input and produces uncompressed output.
        subcommand inflate {? -dictionary bindata ?}
    }

    # Compute a checksum of binary string string using the Adler-32 algorithm.
    subcommand adler32 {string ? initValue ?}

    # Compute a checksum of binary string string using the CRC-32 algorithm.
    subcommand crc32 {string ? initValue ?}

    # @generated end subcommands for zlib
}
