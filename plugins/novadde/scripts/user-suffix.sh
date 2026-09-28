#!/usr/bin/env bash
# UserPromptSubmit: the deployment's `user_message_suffix`, a standing reminder on every turn.
# Empty by default, which is production's state; nothing is emitted while it is empty.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cat >/dev/null 2>&1 || true
suffix="${CLAUDE_PLUGIN_OPTION_USER_MESSAGE_SUFFIX:-}"
[ -z "$suffix" ] && exit 0
printf '%s' "$suffix" | python3 "$here/lib/emit_context.py" UserPromptSubmit
