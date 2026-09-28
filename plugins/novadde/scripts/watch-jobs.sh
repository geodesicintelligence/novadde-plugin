#!/usr/bin/env bash
# The background monitor: one line per job that reaches a terminal state.
#
# Monitors receive no plugin options and cannot resolve ${user_config.*}, so the key has to be
# somewhere a plain process can read it -- which is why it lives only in
# ~/.config/geodesic/model-platform.env, the file every other reader uses too. This sources
# mp-auth.sh for the platform and the data directory; the watcher asks mp-auth.sh for the key again
# on every pass, so a session that starts without one begins watching once it is saved.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/mp-auth.sh"
exec python3 "$here/lib/watch_jobs.py"
