# ASN package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module asn

# Decode a single byte and store it by name in the caller.
meta command asn::asnGetByte {data_var byte_var} {
    bind 2 set
}

# Decode BER length information and store it by name in the caller.
meta command asn::asnGetLength {data_var len_var} {
    bind 2 set
}

# Extract a fixed number of bytes and store them by name in the caller.
meta command asn::asnGetBytes {data_var length bytes_var} {
    bind 3 set
}

# Decode an integer and store it by name in the caller.
meta command asn::asnGetInteger {data_var int_var} {
    bind 2 set
}

# Decode a big integer and store it by name in the caller.
meta command asn::asnGetBigInteger {data_var bignum_var} {
    bind 2 set
}

# Decode an enumeration value and store it by name in the caller.
meta command asn::asnGetEnumeration {data_var enum_var} {
    bind 2 set
}

# Decode an octet string and store it by name in the caller.
meta command asn::asnGetOctetString {data_var string_var} {
    bind 2 set
}

# Decode a sequence payload and store it by name in the caller.
meta command asn::asnGetSequence {data_var sequence_var} {
    bind 2 set
}

# Decode a set payload and store it by name in the caller.
meta command asn::asnGetSet {data_var set_var} {
    bind 2 set
}

# Decode an application wrapper and store requested outputs by name.
meta command asn::asnGetApplication {data_var appNumber_var {content_var {}} {encodingType_var {}}} {
    bind 2 set
    bind 3 set
    bind 4 set
}

# Decode a boolean value and store it by name in the caller.
meta command asn::asnGetBoolean {data_var bool_var} {
    bind 2 set
}

# Decode a UTC time string and store it by name in the caller.
meta command asn::asnGetUTCTime {data_var utc_var} {
    bind 2 set
}

# Decode a bit string and store it by name in the caller.
meta command asn::asnGetBitString {data_var bitstring_var} {
    bind 2 set
}

# Decode an object identifier and store it by name in the caller.
meta command asn::asnGetObjectIdentifier {data_var oid_var} {
    bind 2 set
}
