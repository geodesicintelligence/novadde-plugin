#!/usr/bin/env bash
# The background monitor: one line per job that reaches a terminal state.
#
# Shared OAuth is reread and refreshed on each poll. Login is never opened here.
# Reconnection resumes the existing origin/account partition without duplicate notices.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/mp-auth.sh"
exec python3 "$here/lib/watch_jobs.py" "$@"
