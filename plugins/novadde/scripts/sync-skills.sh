#!/usr/bin/env bash
# Re-vendor the science skills from geodesic-science-skills. Read the diff before committing.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/lib/sync_skills.py" "$(cd "$here/.." && pwd)"
