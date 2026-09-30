#!/usr/bin/env bash
# Platform and cache locations only. Credentials never enter the shell environment.
MP_URL="https://platform.geodesiclab.com"
NOVADDE_DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/novadde}"
mkdir -p "$NOVADDE_DATA" 2>/dev/null || true
export MP_URL NOVADDE_DATA
