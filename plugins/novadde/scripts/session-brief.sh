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

# Two ways to have no working credential, with two different fixes, so the brief keeps them apart:
# no key in the file (save one), and a key the platform refuses (replace it). It names the file,
# never the key; the hint is enough to tell two keys apart.
code=""
if [ -n "$MP_KEY" ]; then
  # The allowance call doubles as the check: its status says whether the key is still good. The
  # status is written after the body, on a line of its own; the newline is a real one, so nothing
  # depends on curl expanding a `\n` in the format.
  reply=$(curl -sS -m 6 -w $'\n%{http_code}' -H "Authorization: Bearer $MP_KEY" \
            "$MP_URL/api/submission-quota" 2>/dev/null) || true
  code="${reply##*$'\n'}"
fi

if [ -z "$MP_KEY" ]; then
  out="$out
Model Platform: $MP_URL, with NO credential: no key in $MP_ENV_SHOWN; run /novadde:setup.
The catalog tools still work (list_models, describe_model, get_model_readme, list_pipelines,
describe_pipeline); everything that submits a run or reads one back will refuse. Tell the user to
run /novadde:setup, which shows them how to save a key in that file from their own terminal. Never
ask for the key in this conversation, do not try to work around it, and do not reach for a
third-party protein API instead."
elif [ "$code" = 401 ] || [ "$code" = 403 ]; then
  out="$out
Model Platform: $MP_URL. It REFUSED the key in $MP_ENV_SHOWN ($MP_KEY_HINT, HTTP $code),
most often because the key was deleted at $MP_URL/keys. The catalog tools still work; everything
that submits a run or reads one back will refuse until the key is replaced. Tell the user to run
/novadde:setup to save a new one there. Never ask for the key in this conversation, and do not try
to work around it."
else
  out="$out
Model Platform: $MP_URL, credentialed as $MP_KEY_HINT."
  quota=""
  [ "$code" = 200 ] && quota=$(printf '%s' "${reply%$'\n'*}" \
                                 | python3 "$here/lib/quota_line.py" 2>/dev/null)
  [ -n "$quota" ] && out="$out
$quota"
fi

# Job notifications. The Model Platform's MCP server tells every client, in its instructions and in
# the descriptions of submit_job ("this deployment watches the job and wakes the conversation on its
# own") and wait_for_job, that a finished job comes back by itself. That is the hosted deployment's
# job_wakeup sweep, and it is served to every client. In a Claude Code session the only thing that
# can report a finished job is this plugin's novadde-jobs monitor, so the brief sets the server's
# claim aside in every session, and promises the monitor only where it can deliver. OFF is the safe
# direction: an agent told OFF gives the user the job's id and checks when asked, and loses nothing
# if a notice arrives after all; an agent told ON ends its turn, and if nothing comes the result is
# lost with it.
#
# * The watcher needs a key, and it reads the same file as everything else (mp-auth.sh), so no key
#   here is no key there. It does look again on every pass, and a key saved mid-session starts it,
#   but this brief is written once, at SessionStart, and says OFF until the next one.
# * A key the platform refused is no better: the watcher stops at its first 401 or 403, having said
#   so once, and a key saved after that needs a new session.
# * Claude Code starts plugin monitors only in interactive CLI sessions, and never where the Monitor
#   tool is unavailable: Bedrock, Vertex and Foundry, or with DISABLE_TELEMETRY or
#   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC set to anything at all (code.claude.com/docs/en/
#   plugins-reference#monitors, /tools-reference#monitor-tool). CLAUDE_CODE_USE_MANTLE is not in
#   that list, but it is another provider switch the CLI reads (2.1.267), and like everything here
#   it can only turn the promise off.
# * CLAUDE_CODE_ENTRYPOINT says which surface started the session. `claude -p` and the Agent SDK run
#   as sdk-*; Claude Desktop sets claude-desktop, and the CLI it starts keeps a value it inherits.
#   Neither is the interactive CLI. Both values are observed (in the user agent the CLI builds from
#   this variable, and in a Desktop session's own environment) rather than documented, which is one
#   more reason they may only turn the promise off. A `claude` started from a terminal that
#   inherited claude-desktop reads OFF too, which costs that user a notice, never a result.
#   Two more values are read from the CLI's own startup code (2.1.267), not observed. A `claude -p`
#   run with CLAUDE_CODE_ACTION set, as the GitHub Action runs it, is named
#   claude-code-github-action instead of sdk-cli, and is just as non-interactive. local-agent is
#   started by Claude Desktop too: the CLI reads the Desktop app's version for it exactly as it does
#   for claude-desktop, and lists it with claude-desktop, claude-desktop-3p and the sdk-* values as
#   a host that renders the CLI's questions itself. The claude-desktop glob keeps claude-desktop-3p.
no_watch=""
if [ -z "$MP_KEY" ]; then
  no_watch="there is no key in $MP_ENV_SHOWN for the job watcher to read"
elif [ "$code" = 401 ] || [ "$code" = 403 ]; then
  no_watch="the platform refused the key in $MP_ENV_SHOWN, and the job watcher stops at the first refusal"
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
