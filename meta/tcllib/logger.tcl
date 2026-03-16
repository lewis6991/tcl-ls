# Logger package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module logger

# Initialize a logging service and return its command token.
meta command logger::init {service}

# Import logger commands into a namespace.
meta command logger::import {args} {
    option -all
    option -force
    option -prefix value
    option -namespace value
}

# Initialize a namespace logger and import its commands.
meta command logger::initNamespace {ns {?level?}}

# List known logger services.
meta command logger::services {}

# Enable logging at and above a level.
meta command logger::enable {level}

# Disable logging at and below a level.
meta command logger::disable {level}

# Set the default log level.
meta command logger::setlevel {level}

# Return the supported log levels.
meta command logger::levels {}

# Return the service command token for a logger service.
meta command logger::servicecmd {service}
