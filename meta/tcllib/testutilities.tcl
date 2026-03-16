# Metadata for Tcllib test helper commands.

# Treat `testing` and `support` bodies as embedded Tcl scripts.
meta command ::testing {script} {
    script-body 1
}
meta command ::support {script} {
    script-body 1
}

# Load test targets and companion packages relative to the caller or helper file.
meta command ::useLocal {fname pname args} {
    source 1 call-source-directory
}
meta command ::useLocalKeep {fname pname args} {
    source 1 call-source-directory
}
meta command ::use {fname pname args} {
    source 1 proc-source-parent
}
meta command ::useKeep {fname pname args} {
    source 1 proc-source-parent
}
meta command ::useAccel {acc fname pname args} {
    source 2 proc-source-parent
}

# Treat helper package gates as effective package requirements.
meta command ::testsNeed {name {version {}}} {
    package 1
}
meta command ::testsNeedTcltest {version} {
    package tcltest
}
