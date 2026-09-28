"""The quota line reports what `GET /api/submission-quota` said, in the unit it said it in.

Two ways it used to put a wrong sentence into every session's brief:

* A refused key answers 401 {"detail": ...}. That has no `limit`, `.get("limit")` is None, and
  None is how the daily shape spells "unmetered" -- so a revoked key was announced as "no daily
  cap".
* Since weekly credits went live (model_platform_api #142), the same route answers with the
  credit wallet: unit "credits", period "week". Read as the daily shape, 37 of 100 credits this
  week became "Submission quota today: 37 of 100 used". The platform's own rule is that a client
  tells the two apart by the unit, never by the numbers (docs/weekly-credits.md).

Fixture shapes are the platform's: SubmissionQuota in app/models.py, credits.view() in
app/credits.py. The refusal body is what the live host answers to a bad key.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import SCRIPTS, Checks, Sandbox, mcp_tools  # noqa: E402

QUOTA_LINE = os.path.join(SCRIPTS, "lib", "quota_line.py")

REFUSED = {"detail": "Sign in or supply an API key."}
DAILY_UNMETERED = {"policy": "unlimited", "limit": None, "used": None, "remaining": None,
                   "utcDay": "2026-09-22", "resetsAt": "2026-09-23T00:00:00Z"}
DAILY = {"policy": "daily_limit", "limit": 5, "used": 2, "remaining": 3,
         "utcDay": "2026-09-22", "resetsAt": "2026-09-23T00:00:00Z"}
CREDITS = {"policy": "weekly_credits", "unit": "credits", "period": "week",
           "limit": 100, "reserved": 0, "periodStartsAt": "2026-09-17T00:00:00Z",
           "resetsAt": "2026-09-24T00:00:00Z", "used": 37, "remaining": 63,
           "balance": {"credits": 250, "held": 0, "available": 250}}
CREDITS_HELD = dict(CREDITS, reserved=12, remaining=51)
# The dev account that was granted 1,000 credits and showed 803: 197 below zero already.
CREDITS_BELOW_ZERO = dict(CREDITS, limit=1000, used=1067, remaining=0,
                          balance={"credits": 0, "held": 0, "available": 0, "owed": 197})
UNKNOWN_UNIT = {"unit": "gpu_seconds", "limit": 3600, "used": 10, "remaining": 3590,
                "resetsAt": "2026-09-24T00:00:00Z"}

CREDIT_LINES = [
    "Credits this week: 37 of 100 used, 63 left, resets 2026-09-24T00:00:00Z.",
    "Purchased credits: 250 available, drawn on only once this week's are used up.",
]


def quota_line(body):
    text = body if isinstance(body, str) else json.dumps(body)
    return subprocess.run([sys.executable, QUOTA_LINE], input=text,
                          capture_output=True, text=True).stdout


def brief_lines(quota_route):
    """The lines of the context session-brief.sh hands the agent."""
    routes = {"GET /api/submission-quota": quota_route, "POST /api/mcp": mcp_tools("get_job")}
    with Sandbox(routes) as box:
        result = box.run("session-brief.sh", stdin=json.dumps({"cwd": "/work"}))
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    return context.splitlines()


def main():
    checks = Checks("test_quota_line")

    print("quota_line.py says nothing it was not told")
    checks.eq("a refused key", quota_line(REFUSED), "")
    checks.eq("an empty object", quota_line({}), "")
    checks.eq("not JSON", quota_line("<html>502</html>"), "")
    checks.eq("a unit it does not know", quota_line(UNKNOWN_UNIT), "")

    print("the daily shape, unchanged")
    checks.eq("unmetered", quota_line(DAILY_UNMETERED),
              "Submission quota: this account has no daily cap.\n")
    checks.eq("capped", quota_line(DAILY),
              "Submission quota today: 2 of 5 used, 3 left, resets 2026-09-23T00:00:00Z.\n")

    print("the weekly credit shape, in its own unit")
    checks.eq("the week, then the purchased balance beside it", quota_line(CREDITS),
              "\n".join(CREDIT_LINES) + "\n")
    # Held, not used: a running job's quote is already in `used`; `reserved` is only what is
    # held for submissions not yet accepted, and the line uses the platform's words for it.
    checks.eq("credits held for submitted work are named", quota_line(CREDITS_HELD).splitlines()[0],
              "Credits this week: 37 of 100 used, 12 held for work already submitted, 51 left, "
              "resets 2026-09-24T00:00:00Z.")
    # Not "0 available": the next purchase covers the part below zero first, and an agent
    # relaying "0" would have the user expect all of what they buy.
    checks.eq("a purchased balance below zero is said as one", quota_line(CREDITS_BELOW_ZERO).splitlines()[1],
              "Purchased credits: balance -197, below zero because runs cost more than quoted after "
              "this week's ran out; the next purchase covers that first.")

    # What the agent actually reads: session-brief.sh's additionalContext.
    print("what reaches the agent")
    allowance = ("Submission quota", "Credits", "Purchased")
    lines = brief_lines({"status": 401, "json": REFUSED})
    checks.eq("a refused key puts no allowance in the brief",
              [line for line in lines if line.startswith(allowance)], [])
    lines = brief_lines({"status": 200, "json": CREDITS})
    checks.eq("the credit wallet reaches it as credits",
              [line for line in lines if line.startswith(allowance)], CREDIT_LINES)

    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
