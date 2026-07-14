#!/usr/bin/env bash
# Bash completion for tv-converter
# Uses argcomplete for intelligent command completion

_tv_converter_completion() {
    # Try venv python first (when installed via deb), then system python
    local python_exec
    if [ -x /var/lib/tv-converter/venv/bin/python ]; then
        python_exec="/var/lib/tv-converter/venv/bin/python"
    else
        python_exec="$(which python3 2>/dev/null || which python 2>/dev/null || echo python3)"
    fi
    
    # Use argcomplete for completion
    export COMP_LINE
    export COMP_POINT
    "$python_exec" -m argcomplete.bash_helper tv-converter 2>/dev/null
}

complete -o bashdefault -o default -o nospace -F _tv_converter_completion tv-converter
