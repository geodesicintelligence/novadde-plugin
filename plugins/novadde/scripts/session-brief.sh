#!/usr/bin/env bash
# SessionStart: the facts a static system prompt cannot carry.
#
# The deployment renders its workspace brief per conversation, with that conversation's own
# directory in it, and composes its MCP brief from a live probe. A plugin's agent body is written
# once, so what is only true of THIS session arrives here: the directory, the credential, the
# allowance, whether anything will report a finished job, and the served verbs when they have
# moved since the agent file was built.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/mp-auth.sh"

input=$(cat 2>/dev/null || true)
cwd=$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    print((json.load(sys.stdin).get("cwd") or "").strip())
except Exception:
    print("")' 2>/dev/null)
[ -z "$cwd" ] && cwd="$PWD"

out="Working directory for this session, which is what \"Where your files go\" names: $cwd"

# Status and allowance use the same MCP authentication as the header helpers.
connection=$("$here/auth.sh" status 2>/dev/null) && connected=true || connected=false
out="$out
$connection"
no_watch=""
if [ "$connected" = true ]; then
  quota=$("$here/auth.sh" call get_usage </dev/null 2>/dev/null | python3 "$here/lib/quota_line.py" 2>/dev/null)
  [ -n "$quota" ] && out="$out
$quota"
else
  out="$out
Production OAuth is not connected. Run /novadde:setup and the installed auth.sh login command in your own terminal. Public catalog reads remain available. Never request credentials in this conversation."
  no_watch="the shared OAuth connection is unavailable; reconnect with /novadde:setup"
fi
if [ -z "$no_watch" ]; then
  for flag in CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY \
              CLAUDE_CODE_USE_MANTLE; do
    # These select a provider when set to a true value, so a 0 or a false leaves the monitor alone.
    case "${!flag:-}" in
      ""|0|false|FALSE|False|no|off) ;;
      *) no_watch="this Claude Code session cannot run plugin monitors ($flag is set)"; break ;;
    esac
  done
fi
if [ -z "$no_watch" ]; then
  # Documented: any value at all, "0" and "false" included, disables the Monitor tool.
  for flag in DISABLE_TELEMETRY CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC; do
    if [ -n "${!flag:-}" ]; then
      no_watch="this Claude Code session cannot run plugin monitors ($flag is set)"
      break
    fi
  done
fi
if [ -z "$no_watch" ]; then
  case "${CLAUDE_CODE_ENTRYPOINT:-}" in
    sdk-*|claude-code-github-action) no_watch="this is a non-interactive session ($CLAUDE_CODE_ENTRYPOINT), where plugin monitors do not run" ;;
    claude-desktop*|local-agent) no_watch="this is a Claude Desktop session ($CLAUDE_CODE_ENTRYPOINT), where plugin monitors do not run" ;;
  esac
fi

out="$out
If the model_platform server's own instructions or a tool's description say this deployment watches each job and wakes the conversation when it finishes, that describes the hosted NovaDDE deployment, not this session: here only the Job notifications line below says whether anything will."
if [ -z "$no_watch" ]; then
  out="$out
Job notifications: ON. A watcher polls your jobs in the background and will tell you when one reaches a terminal state, so end the turn after submit_job instead of waiting on it, and do not loop on wait_for_job."
else
  out="$out
Job notifications: OFF, because $no_watch. Nothing will tell you when a job finishes, and nothing will wake this conversation.
After submit_job, give the user the job's id, tell them you will not hear when it finishes, and offer to check on it later. When they ask, or at the start of your next turn, check it with get_job; do not end a turn expecting to be woken."
fi

built="$here/../prompt/.built-verbs"
if [ -r "$built" ]; then
  now=$("$here/probe-tools.sh" 2>/dev/null | sort | tr '\n' ' ')
  was=$(sort "$built" 2>/dev/null | tr '\n' ' ')
  if [ -n "$now" ] && [ "$now" != "$was" ]; then
    out="$out
The platform's tool list has moved since this plugin was built. It serves exactly these right now
and nothing else: $now"
  fi
fi

printf '%s' "$out" | python3 "$here/lib/emit_context.py" SessionStart NOVADDE_SESSION
