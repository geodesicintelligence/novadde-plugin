#!/usr/bin/env bash
# Compatibility setup entry point; OAuth is the default.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
if [ "${1:-}" = --check ]; then
  exec "$here/auth.sh" status
fi
exec "$here/auth.sh" "${@:-status}"
