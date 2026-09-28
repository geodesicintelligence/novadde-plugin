"""Shared scaffolding for the script tests: a sandbox HOME and a fake `curl` on PATH.

Every script under test reaches the Model Platform through curl. Here curl is a stub that answers
from a route table and logs each call, so the tests need no network and no credential, and can
count requests. The environment is built from nothing rather than inherited, so a developer's own
CLAUDE_PLUGIN_OPTION_* or ~/.config/geodesic file cannot leak in and make a test pass.

Written for the oldest python3 a Mac ships (3.9) as well as CI's.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "plugins", "novadde", "scripts")
KEY = "mp_test_0123456789abcdef"

FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, sys
from urllib.parse import urlsplit

args, method, out, fmt, url, data = sys.argv[1:], None, None, None, None, False
i = 0
while i < len(args):
    arg = args[i]
    if arg in ("-X", "--request"):
        method = args[i + 1]; i += 2; continue
    if arg in ("-o", "--output"):
        out = args[i + 1]; i += 2; continue
    if arg in ("-w", "--write-out"):
        fmt = args[i + 1]; i += 2; continue
    if arg in ("-d", "--data", "--data-raw", "--data-binary"):
        data = True; i += 2; continue
    if arg in ("-H", "--header", "-m", "--max-time"):
        i += 2; continue
    if arg.startswith(("http://", "https://")):
        url = arg
    i += 1
method = method or ("POST" if data else "GET")
path = urlsplit(url or "").path
with open(os.environ["FAKE_CURL_LOG"], "a") as log:
    log.write(json.dumps({"method": method, "path": path}) + "\n")
with open(os.environ["FAKE_CURL_ROUTES"]) as handle:
    route = json.load(handle).get(f"{method} {path}")
if route is None:
    if fmt:
        sys.stdout.write(fmt.replace("%{http_code}", "000"))
    sys.stderr.write("curl: (7) Failed to connect\n")
    sys.exit(7)
body = route["raw"] if "raw" in route else json.dumps(route.get("json"))
if out:
    with open(out, "w") as handle:
        handle.write(body)
else:
    sys.stdout.write(body)
if fmt:
    sys.stdout.write(fmt.replace("%{http_code}", str(route.get("status", 200))))
'''


def mcp_tools(*names):
    """A tools/list answer the way the platform sends it: one SSE frame."""
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": n} for n in names]}}
    return {"status": 200, "raw": "event: message\ndata: " + json.dumps(payload) + "\n\n"}


def key_file(home):
    """Where the key lives: the one file every reader in the plugin reads, under HOME."""
    return os.path.join(home, ".config", "geodesic", "model-platform.env")


class Sandbox:
    """A throwaway HOME with a fake curl first on PATH and, by default, a credential file.

    The credential file is written where a user's is, under the fake HOME, because that path is
    the only one the plugin reads: there is no variable that points the scripts somewhere else.
    It carries a MODEL_PLATFORM_URL line as a lab Mac's does, which the scripts must ignore.
    """

    def __init__(self, routes=None, key=KEY):
        self.root = tempfile.mkdtemp(prefix="novadde-test-")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        self.routes_path = os.path.join(self.root, "routes.json")
        self.log_path = os.path.join(self.root, "curl.log")
        self.env_file = key_file(self.root)
        self.set_routes(routes or {})
        self.add_bin("curl", FAKE_CURL)
        # The scripts call `python3`. Make that the interpreter running the test, so that
        # `/usr/bin/python3 tests/test_x.py` exercises the scripts under 3.9 too.
        self.add_bin("python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        if key:
            os.makedirs(os.path.dirname(self.env_file))
            with open(self.env_file, "w") as handle:
                handle.write("MODEL_PLATFORM_URL=https://platform.test\n")
                handle.write(f"MODEL_PLATFORM_API_KEY={key}\n")
        self.env = {
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.root,
            "FAKE_CURL_ROUTES": self.routes_path,
            "FAKE_CURL_LOG": self.log_path,
            "CLAUDE_PLUGIN_DATA": os.path.join(self.root, "data"),
        }
        for passthrough in ("LANG", "LC_ALL", "TMPDIR"):
            if passthrough in os.environ:
                self.env[passthrough] = os.environ[passthrough]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        shutil.rmtree(self.root, ignore_errors=True)

    def set_routes(self, routes):
        with open(self.routes_path, "w") as handle:
            json.dump(routes, handle)

    def add_bin(self, name, source):
        path = os.path.join(self.bin, name)
        with open(path, "w") as handle:
            handle.write(source)
        os.chmod(path, 0o755)

    def run(self, script, *args, stdin=""):
        return subprocess.run(
            ["bash", os.path.join(SCRIPTS, script), *args],
            input=stdin, env=self.env, capture_output=True, text=True, timeout=60,
        )

    def calls(self):
        try:
            with open(self.log_path) as handle:
                return [json.loads(line) for line in handle if line.strip()]
        except FileNotFoundError:
            return []


class Checks:
    """PASS/FAIL lines in the style of the vendored skills' own self-tests."""

    def __init__(self, name):
        self.name = name
        self.failed = 0

    def eq(self, label, got, want):
        ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            print(f"        got:  {got!r}\n        want: {want!r}")
            self.failed += 1

    def done(self):
        print(f"{self.name}: " + (f"{self.failed} FAILED" if self.failed else "passed"))
        return 1 if self.failed else 0
