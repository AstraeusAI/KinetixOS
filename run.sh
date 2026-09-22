#!/bin/sh
# Launch the Argus shell scaffold against the current session.
exec quickshell -p "$(dirname "$(readlink -f "$0")")/shell" "$@"
