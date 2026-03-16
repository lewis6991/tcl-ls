# Doctools text helper metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module doctools::text

# Reset the text formatter state.
meta command text::begin {}

# Return the formatted text buffer.
meta command text::done {}

# Append text to the current formatter buffer.
meta command text::+ {text}

# Emit an underline for the most recent text fragment.
meta command text::underline {char}

# Queue one or more newline breaks.
meta command text::newline {?increment?}

# Ensure the buffer is positioned at a newline boundary.
meta command text::newline? {}

# Execute a script with temporary indentation.
meta command text::indented {increment script}

# Enable or disable indentation handling.
meta command text::indenting {enable}

# Compute the width needed for a field of elements.
meta command text::field {wvar elements ?index?}
