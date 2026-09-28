#!/usr/bin/env bash
# Everything a person needs to know before asking NovaDDE for work.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/mp-auth.sh"

printf 'Platform      %s\n' "$MP_URL"
# One store, so one line: the MCP connection, the hooks and the job watcher all read this file.
if [ -n "$MP_KEY" ]; then
  printf 'Credential    %s (from %s)\n' "$MP_KEY_HINT" "$MP_ENV_SHOWN"
else
  printf 'Credential    NONE: no key in %s. Run /novadde:setup.\n' "$MP_ENV_SHOWN"
fi
printf 'Tools served  %s\n' "$("$here/probe-tools.sh" 2>/dev/null | wc -l) from $MP_URL/api/mcp"

[ -z "$MP_KEY" ] && exit 0

printf '\nQuota\n'
curl -sS -m 10 -H "Authorization: Bearer $MP_KEY" "$MP_URL/api/submission-quota" 2>/dev/null \
  | python3 "$here/lib/quota_line.py" | sed 's/^/  /'

printf '\nRecent jobs\n'
curl -sS -m 15 -H "Authorization: Bearer $MP_KEY" "$MP_URL/api/jobs?page_size=8" 2>/dev/null \
  | python3 "$here/lib/jobs_table.py" | sed 's/^/  /'

state="$NOVADDE_DATA/watch-state.json"
[ -r "$state" ] && printf '\nWatcher is tracking %s job(s); state in %s\n' \
  "$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$state" 2>/dev/null || echo '?')" "$state"
exit 0
