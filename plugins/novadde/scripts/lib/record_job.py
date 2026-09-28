"""Remember the job and run ids this session submitted.

The control plane cannot see `submit_job` happen -- the agent talks to the platform directly, and
the credential is per user, not per conversation -- so it reconstructs attribution by reading
conversation event logs afterwards. Here the tool result carries the id, so the watcher can mark
which terminal jobs belong to this session and which are the account's other work.
"""
import json
import os
import re
import sys
import time

ID = re.compile(r"\b(?:job|run)-[0-9a-zA-Z]{6,}\b")
KEEP_SECONDS = 7 * 86400


def main() -> int:
    data_dir = os.environ.get("NOVADDE_DATA")
    if not data_dir:
        return 0
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    found = set(ID.findall(json.dumps(event.get("tool_response") or "")))
    if not found:
        return 0
    path = os.path.join(data_dir, "session-jobs.json")
    try:
        with open(path) as handle:
            known = json.load(handle)
    except Exception:
        known = {}
    if not isinstance(known, dict):
        known = {}
    now = int(time.time())
    for job_id in found:
        known.setdefault(job_id, now)
    known = {k: v for k, v in known.items() if isinstance(v, int) and now - v < KEEP_SECONDS}
    tmp = f"{path}.tmp"
    with open(tmp, "w") as handle:
        json.dump(known, handle)
    os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
