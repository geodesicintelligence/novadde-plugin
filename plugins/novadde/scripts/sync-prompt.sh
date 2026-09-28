#!/usr/bin/env bash
# Re-pull the operator prompt from the running deployment, so this repo cannot drift from it.
#
# The prompt lives in the deployment's own configuration, not in any repo, and is read from its
# console's prompt-config endpoint. That console is internal and this repo is published, so its
# address is not written here: set NOVADDE_CONSOLE_URL to it.
#
# This only ever WRITES prompt/system-prompt.md and prompt/response-quality.md, less the passages
# lib/write_prompt.py withholds. Run scripts/build-agent.sh afterwards, and read the diff before
# committing it: the prompt is the operator's text, and a surprise in it is news rather than a
# merge conflict.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
console="${NOVADDE_CONSOLE_URL:-}"
if [ -z "$console" ]; then
  echo "sync-prompt: set NOVADDE_CONSOLE_URL to the deployment console's address." >&2
  exit 2
fi
pool="${NOVADDE_POOL:-}"
url="$console/api/novadde/prompt-config"
[ -n "$pool" ] && url="$url?pool=$pool"

doc=$(curl -sS -m 20 "$url") || {
  echo "sync-prompt: $console did not answer. It is internal: run this from a network that reaches it." >&2
  exit 1
}

printf '%s' "$doc" | python3 "$here/lib/write_prompt.py" "$root"
