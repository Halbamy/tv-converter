#!/usr/bin/env bash
# Bash completion for tv-converter
# Add this to ~/.bashrc or /etc/bash_completion.d/tv-converter

_tv_converter_completion() {
    # Use argcomplete for completion
    export COMP_LINE
    export COMP_POINT
    "$(_tv_converter_get_python)" -m argcomplete.bash_helper "tv-converter" 2>/dev/null || true
}

_tv_converter_get_python() {
    # Find the python executable used by tv-converter
    which python3 2>/dev/null || which python 2>/dev/null || echo "python3"
}

# Register the completion function
complete -o bashdefault -o default -o nospace -F _tv_converter_completion tv-converter
