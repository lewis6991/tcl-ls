# Metadata for Tcllib test helper commands.

# Treat `testing` and `support` bodies as embedded Tcl scripts.
meta effect {::testing script-body 1}
meta effect {::support script-body 1}

# Load test targets and companion packages relative to the caller or helper file.
meta effect {::useLocal source 1 call-source-directory}
meta effect {::useLocalKeep source 1 call-source-directory}
meta effect {::use source 1 proc-source-parent}
meta effect {::useKeep source 1 proc-source-parent}
meta effect {::useAccel source 2 proc-source-parent}

# Treat helper package gates as effective package requirements.
meta effect {::testsNeed package 1}
meta effect {::testsNeedTcltest package tcltest}
