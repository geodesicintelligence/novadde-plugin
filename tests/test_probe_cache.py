"""probe-tools.sh answers from its five-minute cache on a Mac, not only on Linux.

The cache age came from `stat -c %Y`, which is GNU. BSD stat on macOS rejects -c, the `|| echo 0`
fallback made the file's mtime the epoch, every cache looked fifty years old, and every
SessionStart and every /novadde:status went to the network. CI is Linux, where -c works, so the
defect was invisible there. This test gives the script a stat that behaves like the Mac's.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Checks, Sandbox, mcp_tools  # noqa: E402

# stat as macOS ships it: no GNU -c. Everything else goes to the real one.
BSD_STAT = """#!/bin/sh
for arg in "$@"; do
  [ "$arg" = "-c" ] && { echo "stat: illegal option -- c" >&2; exit 1; }
done
exec /usr/bin/stat "$@"
"""


def main():
    checks = Checks("test_probe_cache")
    with Sandbox({"POST /api/mcp": mcp_tools("list_models", "submit_job")}) as box:
        box.add_bin("stat", BSD_STAT)

        def probes():
            return sum(1 for call in box.calls() if call["path"] == "/api/mcp")

        first = box.run("probe-tools.sh")
        checks.eq("the first probe asks the platform", probes(), 1)
        checks.eq("and prints what it serves", first.stdout, "list_models\nsubmit_job\n")

        second = box.run("probe-tools.sh")
        checks.eq("a second probe inside five minutes is served from the cache", probes(), 1)
        checks.eq("with the same answer", second.stdout, first.stdout)

        # A fix that never expires the cache must not pass either.
        cache = os.path.join(box.env["CLAUDE_PLUGIN_DATA"], "tools.txt")
        ten_minutes_ago = time.time() - 600
        os.utime(cache, (ten_minutes_ago, ten_minutes_ago))
        box.run("probe-tools.sh")
        checks.eq("a cache older than five minutes is refreshed", probes(), 2)

    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
