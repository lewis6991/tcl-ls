# Msgcat package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Localize a message string using the active message catalog.
meta command msgcat::mc {args}

# Register a localized message string in the catalog.
meta command msgcat::mcset {locale src dest}

# Load message catalog files from a directory.
meta command msgcat::mcload {langdir}

# Read or change the active locale used for translations.
meta command msgcat::mclocale {args}

# Return the preferred locale search order.
meta command msgcat::mcpreferences {args}

# Read or change the fallback handler for missing translations.
meta command msgcat::mcunknown {args}

# Test whether a message key exists in the catalog.
meta command msgcat::mcexists {args}
