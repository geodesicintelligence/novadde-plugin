"""Tool names out of an MCP `tools/list` reply, one per line.

The endpoint answers as an SSE frame (`event: message` / `data: {...}`), so `response.json()`
raises on it -- the same trap the control plane's own probe documents.
"""
import json
import sys


def main() -> int:
    raw = sys.stdin.read()
    payload = None
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                payload = json.loads(line[6:])
            except ValueError:
                payload = None
            break
    if payload is None:
        try:
            payload = json.loads(raw)
        except ValueError:
            return 1
    tools = (payload.get("result") or {}).get("tools") or []
    names = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
    if not names:
        return 1
    print("\n".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
