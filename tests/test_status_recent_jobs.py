"""/novadde:status lists the account's recent jobs, and says so when it cannot.

The section used to be a python one-liner inside single quotes whose f-string escaped its own
quotes. CPython rejects a backslash there on every version, so status.sh printed a SyntaxError
where the jobs should be. check.sh could not see it: it compiles scripts/lib/*.py and only runs
`bash -n` over the shell, and a single-quoted string is just a string to bash.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Checks, Sandbox, mcp_tools  # noqa: E402

QUOTA = {"status": 200, "json": {"limit": 5, "used": 1, "remaining": 4,
                                 "resetsAt": "2026-09-23T00:00:00Z"}}
TOOLS = mcp_tools("list_jobs", "get_job")


def recent_jobs(stdout):
    """The lines under status.sh's "Recent jobs" heading, up to the next blank line."""
    lines = stdout.splitlines()
    if "Recent jobs" not in lines:
        return None
    start = lines.index("Recent jobs") + 1
    end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
    return lines[start:end]


def status_with(jobs_route):
    routes = {"GET /api/submission-quota": QUOTA, "POST /api/mcp": TOOLS}
    if jobs_route is not None:
        routes["GET /api/jobs"] = jobs_route
    with Sandbox(routes) as box:
        return box.run("status.sh")


def main():
    checks = Checks("test_status_recent_jobs")

    print("an account with jobs")
    result = status_with({"status": 200, "json": {"jobs": [
        {"id": "job-aaa111", "model": "boltzgen", "status": "completed",
         "createdAt": "2026-09-20T01:02:03Z"},
        {"id": "job-bbb222", "model": None, "status": "running"},
    ]}})
    checks.eq("status.sh exits 0", result.returncode, 0)
    checks.eq("nothing on stderr", result.stderr, "")
    checks.eq("one row per job; a null field reads as ?", recent_jobs(result.stdout), [
        "  job-aaa111               boltzgen         completed  2026-09-20T01:02:03Z",
        "  job-bbb222               ?                running",
    ])

    print("an account with none")
    result = status_with({"status": 200, "json": {"jobs": []}})
    checks.eq("says the account is empty", recent_jobs(result.stdout), ["  none on this account"])

    # A refused key proves nothing about the account, so it must not read as an empty one.
    print("a key the platform refuses")
    result = status_with({"status": 401, "json": {"detail": "Sign in or supply an API key."}})
    checks.eq("says why, not 'none on this account'", recent_jobs(result.stdout),
              ["  could not read jobs: Sign in or supply an API key."])

    print("a platform that does not answer")
    result = status_with(None)
    checks.eq("says it could not read them", recent_jobs(result.stdout),
              ["  could not read jobs"])

    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
