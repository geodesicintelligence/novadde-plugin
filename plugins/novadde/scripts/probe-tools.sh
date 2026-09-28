#!/usr/bin/env bash
# What the platform's MCP endpoint serves RIGHT NOW, one name per line.
#
# The brief is composed from this probe rather than from a list in the source, because the
# platform and this plugin ship on different triggers: a verb can appear or be withdrawn without
# a release here. `get_stage_log` was the example: production kept serving it after the platform's
# main had removed it. Unauthenticated on purpose: the catalog half of the endpoint is open and
# tools/list answers 200 with no credential. Cached five minutes, the TTL the control plane uses.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/mp-auth.sh"

CACHE="$NOVADDE_DATA/tools.txt"
TTL=300

if [ -s "$CACHE" ]; then
  # Aged by python, not `stat -c %Y`: that is GNU-only, BSD stat on a Mac rejects -c, and the
  # fallback made every cache look fifty years old, so every probe went to the network.
  age=$(python3 -c 'import os, sys, time; print(int(time.time() - os.path.getmtime(sys.argv[1])))' \
          "$CACHE" 2>/dev/null || echo "$TTL")
  [ "$age" -lt "$TTL" ] && { cat "$CACHE"; exit 0; }
fi

names=$(curl -sS -m 10 -X POST "$MP_URL/api/mcp" \
          -H 'Content-Type: application/json' \
          -H 'Accept: application/json, text/event-stream' \
          -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' 2>/dev/null \
        | python3 "$here/lib/tools_from_sse.py" 2>/dev/null) || names=""

if [ -n "$names" ]; then
  printf '%s\n' "$names" > "$CACHE"
  printf '%s\n' "$names"
  exit 0
fi

# Errs toward the cache, then toward silence: a brief naming a verb the agent cannot find is
# disprovable in one glance at its own tool list, which is the failure this probe exists to avoid.
[ -s "$CACHE" ] && cat "$CACHE"
exit 0
