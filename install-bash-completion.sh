#!/bin/bash
# Install bash completion for tv-converter

set -e

PYTHON_VENV="${1:-.}/venv"
MAIN_PY="${1:-.}/main.py"

if [ ! -x "$PYTHON_VENV/bin/python" ]; then
    echo "Error: Python virtual environment not found at $PYTHON_VENV"
    exit 1
fi

if [ ! -f "$MAIN_PY" ]; then
    echo "Error: main.py not found at $MAIN_PY"
    exit 1
fi

# Register bash completion for tv-converter command
if command -v register-python-argcomplete >/dev/null 2>&1; then
    echo "Registering bash completion for tv-converter..."
    
    # For the system-wide tv-converter command
    if command -v tv-converter >/dev/null 2>&1; then
        # Determine TV_CONVERTER_MAIN_PY for the system command
        TV_CONVERTER_BIN=$(command -v tv-converter)
        # This assumes the system command is in /usr/local/bin or similar
        register-python-argcomplete tv-converter > /etc/bash_completion.d/tv-converter || \
        register-python-argcomplete tv-converter > /usr/local/etc/bash_completion.d/tv-converter || \
        {
            echo "Failed to register completion globally. Installing to ~/.bash_completion.d/"
            mkdir -p ~/.bash_completion.d
            register-python-argcomplete tv-converter > ~/.bash_completion.d/tv-converter
            echo "Added to ~/.bash_completion.d/tv-converter"
            echo "To activate, add this to ~/.bashrc:"
            echo "  source ~/.bash_completion.d/tv-converter"
        }
    else
        echo "tv-converter command not found in PATH"
        echo "Install it first or add it to your PATH"
        exit 1
    fi
else
    echo "argcomplete is not installed or register-python-argcomplete is not available"
    echo "Install argcomplete: pip install argcomplete"
    exit 1
fi

echo "Bash completion installed successfully!"
echo "Restart your terminal or run: source ~/.bashrc"
