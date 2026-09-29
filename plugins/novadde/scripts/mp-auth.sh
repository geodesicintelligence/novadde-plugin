#!/usr/bin/env bash
# The shell's reader of the Model Platform credential. Sourced, never executed.
#
# One store. The key lives in $HOME/.config/geodesic/model-platform.env, mode 600, and nowhere
# else: the MCP connection reads it through the headersHelper in .mcp.json, and the hooks, the
# setup check and the job watcher read it through this file. Both use the same pipeline, and
# tests/test_key_file_credential.py holds them to the same answer on every hand-edit of the file
# it knows, so no two readers can disagree about which key a session has. There used to be a
# second store -- a keychain plugin option the MCP server and the hooks preferred, which monitor
# processes are never given -- and a variable that pointed the scripts at another file. Either one
# let a session be half-connected: tools with no job notifications, or a brief promising a watcher
# that had already exited for want of a key.
#
# The platform is a literal, the same one .mcp.json names. A MODEL_PLATFORM_URL line in the file is
# ignored on purpose: lab Macs carry one pointing at an internal address, and honouring it sent the
# hooks and the watcher -- with the key -- somewhere the MCP server never goes.
#
# For now it is the development deployment, not production. Moving it is this line, the url in
# .mcp.json and .codex.mcp.json, and the pages the README and skills/setup send people to;
# PLATFORM in tests/test_key_file_credential.py holds all of them to one address.
#
# Exports: MP_URL, MP_KEY (may be empty), MP_KEY_HINT, MP_ENV_FILE, MP_ENV_SHOWN, NOVADDE_DATA.

MP_ENV_FILE="$HOME/.config/geodesic/model-platform.env"
# How the file is named to a person or to the agent: the same for everyone, and no user name in it.
MP_ENV_SHOWN='~/.config/geodesic/model-platform.env'
MP_URL="https://dev-platform.geodesiclab.org"

# Read the one key we know, rather than sourcing an arbitrary file into this shell. The pipeline is
# the headersHelper's: an optional leading `export `, a CR (a file saved on Windows), a trailing
# ` # comment`, quotes and stray whitespace all come off, and the last assignment wins, as it
# would if the file were sourced.
MP_KEY=""
if [ -r "$MP_ENV_FILE" ]; then
  MP_KEY=$(sed -n 's/^[[:space:]]*\(export[[:space:]][[:space:]]*\)\{0,1\}MODEL_PLATFORM_API_KEY=//p' "$MP_ENV_FILE" 2>/dev/null \
             | tr -d '\r' | tail -1 | sed 's/[[:space:]][[:space:]]*#.*$//' | tr -d "\"'[:space:]") || MP_KEY=""
fi

# Never print the key. The hint is what a human needs to tell two keys apart.
if [ -n "$MP_KEY" ]; then
  MP_KEY_HINT="${MP_KEY%"${MP_KEY#??????}"}...${MP_KEY#"${MP_KEY%????}"}"
else
  MP_KEY_HINT=""
fi

NOVADDE_DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/novadde}"
mkdir -p "$NOVADDE_DATA" 2>/dev/null || true

export MP_URL MP_KEY MP_KEY_HINT NOVADDE_DATA MP_ENV_FILE MP_ENV_SHOWN
