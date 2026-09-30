#!/usr/bin/env bash
# Everything CI checks, runnable by hand. No network beyond the tool probe.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
status=0
note() { printf '%s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*" >&2; status=1; }

note "== shell syntax =="
for f in "$root"/scripts/*.sh; do bash -n "$f" || fail "bash -n $f"; done

note "== python syntax =="
python3 -m py_compile "$root"/scripts/lib/*.py || fail "py_compile"

note "== shared HTTP helpers are current =="
python3 "$here/lib/build_headers.py" --check || fail "stale generated OAuth helpers"

note "== manifests parse =="
for f in .claude-plugin/plugin.json settings.json .mcp.json \
         hooks/hooks.json monitors/monitors.json \
         .codex-plugin/plugin.json .codex.mcp.json; do
  python3 -c "import json,sys; json.load(open('$root/$f'))" || fail "$f"
done
marketplace="$(cd "$root/../.." && pwd)/.claude-plugin/marketplace.json"
codex_marketplace="$(cd "$root/../.." && pwd)/.agents/plugins/marketplace.json"
# Both marketplaces sit at the repo root, so an installed copy of the plugin has neither and skips
# this. In a checkout the Codex one is required, not merely parsed when present: it is gated on the
# Claude file rather than on itself, so a checkout that loses it fails here. Without it Codex reads
# the Claude marketplace instead, and the install policy, category and section title are gone.
if [ -f "$marketplace" ]; then
  python3 -c "import json; json.load(open('$marketplace'))" || fail "marketplace.json"
  python3 -c "import json; json.load(open('$codex_marketplace'))" || fail ".agents/plugins/marketplace.json"
fi

note "== the agent file is the built one =="
# Rebuilt offline -- from prompt/ and the verbs recorded at the last build -- and compared byte for
# byte. Anchor greps alone passed a file duplicated end to end, reordered, or missing principle 17.
bash "$here/build-agent.sh" --check || fail "agents/novadde.md is not what build-agent.sh builds from prompt/"
# What a rebuild cannot see is the pieces themselves: sync-prompt.sh rewrites the operator's text
# from the control plane, and an empty or truncated pull rebuilds just as faithfully. Frontmatter and
# order are the builder's own and the rebuild covers them; these ask whether each piece has content.
built_bytes=$(wc -c < "$root/agents/novadde.md" 2>/dev/null || echo 0)
[ "$built_bytes" -gt 20000 ] || fail "agents/novadde.md looks unbuilt ($built_bytes bytes)"
grep -q '^Your name is NovaDDE' "$root/agents/novadde.md" || fail "the operator prompt is missing"
grep -q '^## Where your files go' "$root/agents/novadde.md" || fail "the workspace brief is missing"
grep -q '^## Structural biology on this deployment' "$root/agents/novadde.md" || fail "the MCP brief is missing"
grep -q '</RESPONSE_QUALITY>' "$root/agents/novadde.md" || fail "the response-quality block is missing"

note "== vendored skills resolve their scripts =="
python3 "$here/lib/check_skills.py" "$root" || fail "skill script paths"

note "== every skill has parsable frontmatter =="
python3 - "$root" <<'PY' || fail "skill frontmatter"
import os, sys
root = sys.argv[1]
bad = []
for name in sorted(os.listdir(os.path.join(root, "skills"))):
    doc = os.path.join(root, "skills", name, "SKILL.md")
    if not os.path.isfile(doc):
        if not name.startswith("."):
            bad.append(f"{name}: no SKILL.md")
        continue
    with open(doc, encoding="utf-8") as handle:
        text = handle.read()
    if not text.startswith("---") or "\n---" not in text[3:]:
        bad.append(f"{name}: no frontmatter")
    elif "description:" not in text[: text.find("\n---", 3)]:
        bad.append(f"{name}: frontmatter has no description")
for entry in bad:
    print(f"FAIL {entry}", file=sys.stderr)
raise SystemExit(1 if bad else 0)
PY

# The scripts' own behaviour, against a fake curl. The tests live at the repo root, outside the
# plugin directory, so an install does not ship them. In a checkout -- where the marketplace
# manifest sits beside them -- they are required; an installed copy has none to run.
tests="$(cd "$root/../.." && pwd)/tests"
if [ -f "$marketplace" ]; then
  note "== script behaviour =="
  ran=0
  for t in "$tests"/test_*.py; do
    [ -e "$t" ] || continue
    ran=$((ran + 1))
    python3 "$t" || fail "$(basename "$t")"
  done
  [ "$ran" -gt 0 ] || fail "no tests found under $tests"
fi

if command -v claude >/dev/null 2>&1; then
  note "== claude plugin validate =="
  # The plugin and the marketplace are two manifests. Pointed at a directory holding both,
  # `validate` reports only the marketplace -- which is why they live at different paths here.
  claude plugin validate "$root" --strict || fail "claude plugin validate (plugin)"
  repo="$(cd "$root/../.." && pwd)"
  if [ -f "$repo/.claude-plugin/marketplace.json" ]; then
    claude plugin validate "$repo" --strict || fail "claude plugin validate (marketplace)"
  fi
else
  note "== claude plugin validate: skipped, no claude on PATH =="
fi

[ "$status" -eq 0 ] && note "all checks passed"
exit "$status"
