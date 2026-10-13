# Editor help for the commands supplied to safe Tcl metadata plugins.
meta module TclLSPlugin {
    # Read one source word as data, without executing it.
    #
    # `index` starts at 1 and includes the command name.
    # Resolve literals and whole-variable words with known literal values.
    # Return a read-only source item with `id`, `text`, and `grouped`, or an empty string
    # when unknown. The source ID is valid only in this plugin invocation.
    # `text` is raw source content without outer braces or quotes; escapes stay literal.
    # Derive new source items with `slice`; editing fields does not change the source.
    meta command tcl_lsp::word {index}

    # Read a known literal variable value in the caller's scope.
    #
    # `name` is the variable name without `$`.
    # Return a read-only source item with `id`, `text`, and `grouped`.
    # Unknown, changed, or ambiguous values return an empty string.
    # The source ID points to the original literal assignment.
    # `text` is raw source content without outer braces or quotes; escapes stay literal.
    # Derive new source items with `slice`; editing fields does not change the source.
    meta command tcl_lsp::variable {name}

    # Split a source item into a Tcl list of read-only source items.
    #
    # `value` must be a source item supplied by the plugin source queries.
    # Each returned item is a dictionary.
    #
    # **Fields in each item**
    #
    # - `id`: opaque source ID, valid only in this invocation.
    # - `text`: raw source content without outer braces or quotes. Escapes stay literal.
    # - `grouped`: 1 for an item enclosed in braces or quotes; otherwise 0.
    #
    # Each ID preserves the item's original location. Invalid lists raise a Tcl error.
    # Derive new source items with `slice`; editing fields does not change the source.
    meta command tcl_lsp::source_list_items {value}

    # Take a substring and preserve its original source location.
    #
    # - `value`: a read-only source item supplied by the plugin source queries.
    # - `start`: first character index, starting at 0.
    # - `end`: exclusive end index; `end` means the end of the string.
    #
    # Return a read-only source item with `id`, `text`, and `grouped`.
    # `text` is raw source content; escapes stay literal.
    # Editing fields does not change the source; use this helper to derive a new item.
    # Invalid ranges raise a Tcl error. Return the source ID in `params {items ...}`.
    meta command tcl_lsp::slice {value start end}

}
