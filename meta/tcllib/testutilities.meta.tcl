# Metadata for Tcllib test helper commands.

# Treat `testing` and `support` bodies as embedded Tcl scripts.
meta command ::testing {script} {
    enter tcl body 1
}
meta command ::support {script} {
    enter tcl body 1
}

# Load test targets and companion packages relative to the caller or helper file.
meta command ::useLocal {fname pname args} {
    source 1 caller
}
meta command ::useLocalKeep {fname pname args} {
    source 1 caller
}
meta command ::use {fname pname args} {
    source 1 definition
}
meta command ::useKeep {fname pname args} {
    source 1 definition
}
meta command ::useAccel {acc fname pname args} {
    source 2 definition
}

# Treat helper package gates as effective package requirements.
meta command ::testsNeed {name {version {}}} {
    package select 1
}
meta command ::testsNeedTcltest {version} {
    package literal tcltest
}
