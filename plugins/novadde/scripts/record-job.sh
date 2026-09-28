#!/usr/bin/env bash
# PostToolUse on a submission: remember which ids this session started.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/mp-auth.sh"
python3 "$here/lib/record_job.py" 2>/dev/null || true
exit 0
