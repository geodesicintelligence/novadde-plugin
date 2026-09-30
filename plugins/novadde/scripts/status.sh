#!/usr/bin/env bash
# Account, quota and recent jobs through the shared MCP OAuth connection.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
"$here/auth.sh" status || exit $?
printf '\nQuota\n'
"$here/auth.sh" call get_usage </dev/null | python3 "$here/lib/quota_line.py"
printf '\nRecent jobs\n'
printf '{"limit":8}' | "$here/auth.sh" call list_jobs | python3 "$here/lib/jobs_table.py"
