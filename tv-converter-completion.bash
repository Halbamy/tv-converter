#!/usr/bin/env bash
# Bash completion for tv-converter
# Uses argcomplete for intelligent command completion.

_tv_converter_argcomplete_run() {
    if [ -z "${_ARC_DEBUG-}" ]; then
        "$@" 8>&1 9>&2 1>/dev/null 2>&1
    else
        "$@" 8>&1 9>&2 1>&9 2>&1
    fi
}

_tv_converter_completion() {
    local IFS=$'\013'
    local suppress_space=0

    if compopt +o nospace 2>/dev/null; then
        suppress_space=1
    fi

    COMPREPLY=($(IFS="$IFS" \
        COMP_LINE="$COMP_LINE" \
        COMP_POINT="$COMP_POINT" \
        COMP_TYPE="$COMP_TYPE" \
        _ARGCOMPLETE_COMP_WORDBREAKS="$COMP_WORDBREAKS" \
        _ARGCOMPLETE=1 \
        _ARGCOMPLETE_SHELL="bash" \
        _ARGCOMPLETE_SUPPRESS_SPACE="$suppress_space" \
        _tv_converter_argcomplete_run "${1:-tv-converter}"))

    if [ $? -ne 0 ]; then
        unset COMPREPLY
    elif [ "$suppress_space" -eq 1 ] && [[ "${COMPREPLY-}" =~ [=/:]$ ]]; then
        compopt -o nospace
    fi
}

complete -o bashdefault -o default -o nospace -F _tv_converter_completion tv-converter
