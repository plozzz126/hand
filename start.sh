#!/usr/bin/env bash
set -e
cd -- "$(dirname -- "$0")"

if command -v python3.12 >/dev/null 2>&1; then
    exec python3.12 run.py "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 run.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python run.py "$@"
else
    printf '%s\n' 'Python was not found. Install 64-bit Python 3.12 from https://www.python.org/downloads/' >&2
    exit 1
fi
