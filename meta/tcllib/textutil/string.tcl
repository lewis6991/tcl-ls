# Textutil::string package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module textutil::string

# Uppercase the first character of a string.
meta command textutil::string::cap {text}

# Remove the first character from a string.
meta command textutil::string::chop {text}

# Uppercase the first character of each word.
meta command textutil::string::capEachWord {sentence}

# Compute the longest common prefix of one or more strings.
meta command textutil::string::longestCommonPrefix {args}

# Compute the longest common prefix of a list of strings.
meta command textutil::string::longestCommonPrefixList {items}

# Remove the last character from a string.
meta command textutil::string::tail {text}

# Lowercase the first character of a string.
meta command textutil::string::uncap {text}
