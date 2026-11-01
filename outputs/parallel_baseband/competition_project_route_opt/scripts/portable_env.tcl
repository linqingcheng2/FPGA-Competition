# No dependency on a Codex installation or a particular user account.
if {[info exists ::env(BASEBAND_PYTHON)] && $::env(BASEBAND_PYTHON) ne ""} {
    set ::baseband_python $::env(BASEBAND_PYTHON)
} else {
    set ::baseband_python [auto_execok python]
    if {$::baseband_python eq ""} {error "Set BASEBAND_PYTHON to Python 3.12 python.exe"}
}
