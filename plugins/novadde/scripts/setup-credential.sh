#!/usr/bin/env bash
# The plugin's credential: the one key in ~/.config/geodesic/model-platform.env.
#
#   --check            report what is configured and whether the platform accepts it
#   --key mp_...       verify a key, then store it in that file
#
# One store. The MCP connection (the headersHelper in .mcp.json), the hooks and the background job
# watcher all read that file -- the lab's existing convention (`geodesic-model-platform`), mode 600,
# outside every repo -- and there is no plugin option for the key any more, so nothing here tells
# anyone to set one. The setup skill has the user save the key from their own terminal and runs
# only --check, because --key takes the key on argv, where the process list and a transcript see it.
#
# There is no way to mint a key from here. --login did it with an email and a password through
# /api/auth/login, and the platform signs no one in that way any more: it signs people in with Google
# through Identity Platform, and that route answers 503 on both deployments. A key is minted on the
# web app's API Keys page, as the README and /novadde:setup say.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/mp-auth.sh"

usage() { sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; }

verify() {  # $1 = key; prints the account line, returns non-zero when refused
  local key="$1" body code
  body=$(curl -sS -m 15 -o /tmp/novadde-verify.$$ -w '%{http_code}' \
           -H "Authorization: Bearer $key" "$MP_URL/api/auth/me" 2>/dev/null) || body=000
  code="$body"
  if [ "$code" = "200" ]; then
    python3 -c '
import json, sys
try:
    me = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit
print("accepted for", me.get("email") or me.get("id") or "this account")
' /tmp/novadde-verify.$$ 2>/dev/null
    rm -f /tmp/novadde-verify.$$
    return 0
  fi
  rm -f /tmp/novadde-verify.$$
  printf 'refused with HTTP %s\n' "$code"
  return 1
}

store() {  # $1 = key
  local key="$1" dir
  dir=$(dirname "$MP_ENV_FILE")
  mkdir -p "$dir" && chmod 700 "$dir" 2>/dev/null || true
  umask 077
  cat > "$MP_ENV_FILE" <<EOF
# Written by the novadde plugin's /novadde:setup. Mode 600, outside every repo.
MODEL_PLATFORM_URL=$MP_URL
MODEL_PLATFORM_API_KEY=$key
EOF
  chmod 600 "$MP_ENV_FILE"
  printf 'stored in %s\n' "$MP_ENV_FILE"
}

case "${1:---check}" in
  --check)
    printf 'Platform: %s\n' "$MP_URL"
    if [ -z "$MP_KEY" ]; then
      printf 'Credential: none configured; no key in %s.\n' "$MP_ENV_SHOWN"
      exit 3
    fi
    printf 'Credential: %s from %s\n' "$MP_KEY_HINT" "$MP_ENV_SHOWN"
    verify "$MP_KEY" || exit 4
    ;;
  --key)
    key="${2:-}"
    [ -z "$key" ] && { echo "usage: $0 --key mp_..." >&2; exit 2; }
    case "$key" in mp_*|bnx_*) ;; *) echo "that does not look like a platform API key (they start with mp_)" >&2; exit 2;; esac
    verify "$key" || exit 4
    store "$key"
    printf 'Start a new session: the MCP connection reads the key when it connects, and the hooks\n'
    printf 'and the job watcher read it from the same file.\n'
    ;;
  -h|--help) usage ;;
  *) usage; exit 2 ;;
esac
