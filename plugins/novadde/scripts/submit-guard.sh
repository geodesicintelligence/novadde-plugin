#!/usr/bin/env bash
# PreToolUse: the deployment's `deny_parent_job_submission`, off by default there and here.
#
# A deny is the only control that holds in every permission mode, which is why the control plane
# uses one rather than a prompt rule.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cat >/dev/null 2>&1 || true
case "${CLAUDE_PLUGIN_OPTION_READ_ONLY:-false}" in
  true|1|yes|on) python3 "$here/lib/deny_submit.py" ;;
  *) exit 0 ;;
esac
