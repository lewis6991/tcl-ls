# Helper command effect metadata for tcl-ls.

# Treat `testing` and `support` bodies as embedded Tcl scripts.
meta effect testutilities.tcl {::testing script-body 1}
meta effect testutilities.tcl {::support script-body 1}

# Load test targets and companion packages relative to the caller or helper file.
meta effect testutilities.tcl {::useLocal source 1 call-source-directory}
meta effect testutilities.tcl {::useLocalKeep source 1 call-source-directory}
meta effect testutilities.tcl {::use source 1 proc-source-parent}
meta effect testutilities.tcl {::useKeep source 1 proc-source-parent}
meta effect testutilities.tcl {::useAccel source 2 proc-source-parent}

# Treat helper package gates as effective package requirements.
meta effect testutilities.tcl {::testsNeed package 1}
meta effect testutilities.tcl {::testsNeedTcltest package tcltest}
