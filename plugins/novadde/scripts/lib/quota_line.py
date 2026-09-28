"""A line or two about the account's allowance, or nothing at all.

`GET /api/submission-quota` answers in one of two shapes, and the platform's rule is that a client
tells them apart by the unit, never by the numbers (model_platform_api docs/weekly-credits.md):

* daily submissions, the shape before weekly credits went live -- {policy, limit, used,
  remaining, utcDay, resetsAt}, no `unit`. `limit`, `used` and `remaining` are null together for
  an account nothing meters.
* weekly credits, since activation -- {unit: "credits", period: "week", limit, used, reserved,
  remaining, resetsAt, balance: {credits, held, available, owed}}. `remaining` is the week's
  alone; the purchased balance is a second figure beside it and is never added in, because an
  account whose week is spent may still have bought credits to keep going. A running job's quote
  is already in `used`; `reserved` is only what is held for submissions not yet accepted, in the
  platform's words "held for work already submitted". `owed` is how far below zero the purchased
  balance stands -- runs paid from it that cost more than quoted after the week ran out -- while
  `available` reads 0, and it is said as the negative balance it is: the next purchase covers it
  first, which "0 available" would hide from anyone about to buy. A platform before 2026-09-24
  does not send it.

Silence on any other shape, a 401's {"detail": ...} included: a session brief that guesses at a
quota is worse than one that omits it, because the prompt tells the agent never to invent a
number for this.
"""
import json
import sys


def daily(quota: dict) -> list:
    limit = quota["limit"]
    if limit is None:
        return ["Submission quota: this account has no daily cap."]
    used, remaining, resets = quota.get("used"), quota.get("remaining"), quota.get("resetsAt")
    if used is None or remaining is None:
        return []
    return [f"Submission quota today: {used} of {limit} used, {remaining} left, resets {resets}."]


def credits(quota: dict) -> list:
    limit, used, remaining = quota["limit"], quota.get("used"), quota.get("remaining")
    if limit is None or used is None or remaining is None:
        return []
    held = f", {quota['reserved']} held for work already submitted" if quota.get("reserved") else ""
    lines = [f"Credits this {quota.get('period') or 'period'}: {used} of {limit} used{held}, "
             f"{remaining} left, resets {quota.get('resetsAt')}."]
    balance = quota.get("balance")
    if isinstance(balance, dict) and balance.get("available") is not None:
        owed = balance.get("owed")
        if isinstance(owed, int) and not isinstance(owed, bool) and owed > 0:
            lines.append(f"Purchased credits: balance -{owed}, below zero because runs cost more than "
                         f"quoted after this {quota.get('period') or 'period'}'s ran out; the next "
                         f"purchase covers that first.")
        else:
            lines.append(f"Purchased credits: {balance['available']} available, drawn on only once "
                         f"this {quota.get('period') or 'period'}'s are used up.")
    return lines


def main() -> int:
    try:
        quota = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(quota, dict) or "limit" not in quota:
        return 0
    unit = quota.get("unit")
    if unit is None:
        lines = daily(quota)
    elif unit == "credits":
        lines = credits(quota)
    else:
        lines = []
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
