# Tk package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module Tk

# Create a button widget.
meta command button {pathName ?options?}

# Create or query event bindings.
meta command bind {window ?sequence? ?script?}

# Create a canvas widget.
meta command canvas {pathName ?options?}

# Create a checkbutton widget.
meta command checkbutton {pathName ?options?}

# Destroy one or more widgets.
meta command destroy {window ?window ...?}

# Create an entry widget.
meta command entry {pathName ?options?}

# Generate or inspect Tk events.
meta command event {subcommand args}

# Create, configure, or inspect named fonts.
meta command font {subcommand args}

# Query or change keyboard focus.
meta command focus {args}

# Create a frame widget.
meta command frame {pathName ?options?}

# Manage pointer or keyboard grabs.
meta command grab {subcommand args}

# Manage widgets with the grid geometry manager.
meta command grid {args}

# Create or manage Tk images.
meta command image {subcommand args}

# Create a label widget.
meta command label {pathName ?options?}

# Create a labelframe widget.
meta command labelframe {pathName ?options?}

# Create a listbox widget.
meta command listbox {pathName ?options?}

# Lower a window in the stacking order.
meta command lower {window ?belowThis?}

# Create a menu widget.
meta command menu {pathName ?options?}

# Create a menubutton widget.
meta command menubutton {pathName ?options?}

# Create a message widget.
meta command message {pathName ?options?}

# Manage the Tk option database.
meta command option {subcommand args}

# Manage widgets with the pack geometry manager.
meta command pack {args}

# Create a panedwindow widget.
meta command panedwindow {pathName ?options?}

# Manage widgets with the place geometry manager.
meta command place {args}

# Create a radiobutton widget.
meta command radiobutton {pathName ?options?}

# Raise a window in the stacking order.
meta command raise {window ?aboveThis?}

# Create a scale widget.
meta command scale {pathName ?options?}

# Create a scrollbar widget.
meta command scrollbar {pathName ?options?}

# Create a spinbox widget.
meta command spinbox {pathName ?options?}

# Create a text widget.
meta command text {pathName ?options?}

# Open a directory chooser dialog.
meta command tk_chooseDirectory {?option value ...?}

# Open a message box dialog.
meta command tk_messageBox {?option value ...?}

# Wait for a Tk variable, visibility change, or window to complete.
meta command tkwait {variable|visibility|window name}

# Set the current application palette.
meta command tk_setPalette {?background? ?option value ...?}

# Create a toplevel widget.
meta command toplevel {pathName ?options?}

# Query Tk window information.
meta command winfo {option ?arg ...?}

# Query or configure window manager state.
meta command wm {option window ?arg ...?}
