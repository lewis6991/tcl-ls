# Cmdline package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Return the application name for use in command-line error messages.
meta command cmdline::getArgv0 {}

# Parse the next option from an argv-style list.
# Updates the variables named by optVar and valVar with the parsed option
# name and value, and mutates argvVar by removing the consumed arguments.
meta command cmdline::getopt {argvVar optstring optVar valVar} {
    bind 3 set
    bind 4 set
}

# Parse the next known option from an argv-style list.
# Updates the variables named by optVar and valVar with the parsed option
# name and value, and mutates argvVar by removing the consumed arguments.
meta command cmdline::getKnownOpt {argvVar optstring optVar valVar} {
    bind 3 set
    bind 4 set
}
