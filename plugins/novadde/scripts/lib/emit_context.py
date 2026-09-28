"""Wrap stdin as a hook's additionalContext.

argv[1] is the hook event name; argv[2], when given, wraps the text in that tag.
"""
import json
import sys


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else "SessionStart"
    tag = sys.argv[2] if len(sys.argv) > 2 else ""
    text = sys.stdin.read().rstrip("\n")
    if not text:
        return 0
    if tag:
        text = f"<{tag}>\n{text}\n</{tag}>"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
