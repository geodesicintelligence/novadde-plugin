#!/usr/bin/env bash
# Bundled authentication command. Browser login is only ever an explicit user command.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/lib/oauth_client.py" "$@"
