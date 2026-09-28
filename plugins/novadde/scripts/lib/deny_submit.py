"""The PreToolUse refusal, in the deployment's own words (`_UNGRADED_NO_SUBMIT`)."""
import json

REASON = (
    "You cannot submit a job on this deployment: submit_job is denied to you, because a job you "
    "submit yourself reaches those GPUs while skipping every check above. If a request needs a "
    "model to run, say so rather than assembling a substitute. (An operator turns this off with "
    "the read_only setting of the novadde plugin.)"
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": REASON,
    }
}))
