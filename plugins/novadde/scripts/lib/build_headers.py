"""Generate root-independent HTTP helpers from the single shared auth module."""
import base64
import json
from pathlib import Path
import shlex
import sys
import zlib


def helper(root):
    encoded = base64.b64encode(zlib.compress((root / "scripts/lib/oauth_client.py").read_bytes())).decode()
    code = "import base64,zlib;exec(compile(zlib.decompress(base64.b64decode(%r)),'novadde-auth','exec'))" % encoded
    return "python3 -c " + shlex.quote(code) + " headers"


def main():
    root = Path(__file__).resolve().parents[2]
    expected = helper(root)
    for name, field in [(".mcp.json", "headersHelper"), (".codex.mcp.json", "http_headers_helper")]:
        path = root / name
        value = json.loads(path.read_text())
        server = value["mcpServers"]["model_platform"]
        if "--check" in sys.argv:
            if server[field] != expected or server["url"] != "https://platform.geodesiclab.com/api/mcp":
                raise SystemExit("Generated HTTP helper is stale: " + name)
        else:
            server[field] = expected
            server["url"] = "https://platform.geodesiclab.com/api/mcp"
            path.write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    main()
