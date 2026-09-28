#!/usr/bin/env bash
# Assemble agents/novadde.md -- the whole system prompt of a NovaDDE session.
#
# The order is the one `prompt_config.inject_into_launch` produces under `replace` mode, which is
# what the deployment runs: the operator's prompt FIRST (it is about to be the whole prompt, so
# the identity leads), then the deployment's briefs, then the response-quality block last. In
# `append` mode the briefs come first instead; this plugin only ever reproduces `replace`, because
# an agent run as the main session replaces Claude Code's prompt whether we like it or not.
#
#   build-agent.sh           probe the platform for its verbs, record them in prompt/.built-verbs,
#                            and write agents/novadde.md.
#   build-agent.sh --check   offline: rebuild from prompt/ and the verbs recorded at the last build
#                            into a temp file, and compare with agents/novadde.md byte for byte.
#                            Writes nothing in the tree. This is what check.sh (and CI) runs.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
server="model_platform"
agent="$root/agents/novadde.md"
built_verbs="$root/prompt/.built-verbs"

# assemble VERBS OUT -- the one assembly both modes share. VERBS is one tool name per line.
assemble() {
  local verbs_raw="$1" out="$2" verbs mcp_brief
  verbs=$(printf '%s\n' "$verbs_raw" | sed 's/^/`/; s/$/`/' | paste -sd, - | sed 's/,/, /g')
  mcp_brief=$(sed -e "s/{server}/$server/g" "$root/prompt/mcp-brief.md" \
              | awk -v v="$verbs" '{gsub(/\{verbs\}/, v); print}')
  {
    cat <<'FRONT'
---
name: novadde
description: NovaDDE, Geodesic Intelligence's AI co-scientist for drug discovery. Designs peptides, antibodies and protein binders by running the lab's own GPU models, confirms every submission with the user first, and keeps evidence tiers apart. Built from the deployment's own prompt.
---
FRONT
    echo
    cat "$root/prompt/system-prompt.md"
    echo
    cat "$root/prompt/workspace-brief.md"
    echo
    printf '%s\n' "$mcp_brief"
    echo
    cat "$root/prompt/response-quality.md"
  } > "$out"
}

case "${1:-}" in
  "") mode=build ;;
  --check) mode=check ;;
  -h|--help) echo "usage: build-agent.sh [--check]"; exit 0 ;;
  *) echo "usage: build-agent.sh [--check]" >&2; exit 2 ;;
esac

if [ "$mode" = check ]; then
  # Absent (or blank) and unreadable are two faults with two fixes, so the read is not silenced:
  # a file that is there but cannot be read -- a permission, a PATH with no `cat` -- shows the
  # reader's own error, instead of sending someone to rebuild a record that is not missing.
  verbs_raw=""
  if [ -s "$built_verbs" ]; then
    verbs_raw=$(cat "$built_verbs") || {
      echo "build-agent --check: prompt/.built-verbs is there but could not be read (see above)." >&2
      exit 1
    }
  fi
  if [ -z "$verbs_raw" ]; then
    echo "build-agent --check: prompt/.built-verbs is missing or empty, so there is nothing to" >&2
    echo "                     rebuild the MCP brief from. Run scripts/build-agent.sh." >&2
    exit 1
  fi
  rebuilt=$(mktemp "${TMPDIR:-/tmp}/novadde-agent.XXXXXX")
  trap 'rm -f "$rebuilt"' EXIT
  assemble "$verbs_raw" "$rebuilt"
  if cmp -s "$agent" "$rebuilt"; then
    echo "agents/novadde.md is what prompt/ and prompt/.built-verbs build"
    exit 0
  fi
  {
    echo "build-agent --check: agents/novadde.md is not what prompt/ builds. The diff, committed"
    echo "                     -> rebuilt (first 60 lines):"
    diff -u --label "agents/novadde.md (committed)" --label "rebuilt from prompt/" \
      "$agent" "$rebuilt" | head -n 60 || true
    echo "Run scripts/build-agent.sh and commit its output; never edit agents/novadde.md by hand."
  } >&2
  exit 1
fi

verbs_raw=$("$here/probe-tools.sh" 2>/dev/null || true)
if [ -z "$verbs_raw" ]; then
  echo "build-agent: the platform's tool list could not be read; refusing to write a brief that" >&2
  echo "             names verbs nobody has confirmed. Re-run when the platform answers." >&2
  exit 1
fi
printf '%s\n' "$verbs_raw" > "$built_verbs"
assemble "$verbs_raw" "$agent"

printf 'wrote agents/novadde.md (%s bytes, %s tools in the brief)\n' \
  "$(wc -c < "$agent")" "$(printf '%s\n' "$verbs_raw" | wc -l)"
