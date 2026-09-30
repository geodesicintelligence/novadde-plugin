"""The recent-jobs table /novadde:status prints, or one line saying why there is none.

`GET /api/jobs` answers {"jobs": [...]}. Anything else -- a 401's {"detail": ...}, or nothing at
all because the platform did not answer -- is reported as unreadable rather than as an empty
account: "none on this account" is a claim about the account, and a refused key proves nothing
about it.

This used to be a one-liner inside status.sh's single quotes, where the escaped quotes it needed
made it a SyntaxError on every Python. Here check.sh compiles it.
"""
import json
import sys

LIMIT = 8


def cell(value, blank="?"):
    return blank if value is None or value == "" else str(value)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        payload = None
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        detail = payload.get("detail") if isinstance(payload, dict) else None
        print("could not read jobs" + (f": {detail}" if isinstance(detail, str) and detail else ""))
        return 0
    rows = [job for job in jobs if isinstance(job, dict)][:LIMIT]
    if not rows:
        print("none on this account")
    for job in rows:
        line = "{:<24} {:<16} {:<10} {}".format(
            cell(job.get("id")), cell(job.get("model")), cell(job.get("status")),
            cell((job.get("createdAt") or job.get("created_at")), ""),
        )
        print(line.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
