"""Shared production OAuth for MCP, hooks and the Claude watcher (Python 3.9+).

The HTTP header commands embed this exact module at build time because Codex starts
HTTP helpers in the session directory, without a plugin-root environment variable.
Only the `headers` command emits a credential, to the host's private header pipe.
"""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

ISSUER = "https://platform.geodesiclab.com"
RESOURCE = ISSUER + "/api/mcp"
CLIENT = ISSUER + "/api/oauth/clients/novadde-plugin.json"
BINDING = {"issuer": ISSUER, "resource": RESOURCE, "client_id": CLIENT}
SCOPES = "jobs:read jobs:write"


class AuthError(Exception):
    """Safe, credential-free diagnostic."""


class NetworkError(AuthError):
    pass


class Rejected(AuthError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid argument values, including an old --key
        # invocation. Usage contains no user data; the diagnostic must not either.
        self.print_usage(sys.stderr)
        self.exit(2, "Unsupported arguments. Use --help; keep credentials off command arguments.\n")


def directory():
    return Path.home() / ".config" / "geodesic"


def credential_path():
    return directory() / "novadde-oauth.json"


def load():
    try:
        path = credential_path()
        value = json.loads(path.read_text())
        if path.stat().st_mode & 0o777 != 0o600:
            os.chmod(path, 0o600)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise AuthError("Unreadable authentication store. Run the installed auth.sh login command.") from None


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + "-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def locked():
    directory().mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(directory() / "novadde-oauth.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def request(url, data=None, token=None, form=False):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        # Credentials and code exchanges must never follow an unexpected redirect.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(req, timeout=3) as response:
            body = response.read(4 * 1024 * 1024).decode()
    except urllib.error.HTTPError as exc:
        # Do not include response bodies/URLs: an upstream error can echo a credential.
        error_type = Rejected if exc.code in (401, 403) else AuthError
        raise error_type("Platform refused authentication (HTTP %d)." % exc.code) from None
    except (OSError, ValueError):
        raise NetworkError("Cannot reach the production platform. Try again when connected.") from None
    try:
        if not body.strip():
            return {}
        if body.lstrip().startswith("{"):
            return json.loads(body)
        frames = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]
        return next(frame for frame in frames if frame.get("id") == 1)
    except (ValueError, StopIteration):
        raise NetworkError("The platform returned an unreadable response.") from None


def rpc(name, arguments=None, token=None):
    payload = request(RESOURCE, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": arguments or {}}}, token)
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        raise AuthError("The platform refused the MCP call. Check access with auth.sh status.")
    if "structuredContent" in result:
        return result["structuredContent"]
    try:
        return json.loads(result["content"][0]["text"])
    except (ValueError, KeyError, IndexError):
        raise AuthError("The platform returned an unreadable MCP result.") from None


def legacy_key():
    try:
        text = (directory() / "model-platform.env").read_text()
    except OSError:
        raise AuthError("No legacy API-key file. Save a production key locally before selecting legacy mode.") from None
    matches = re.findall(r"^\s*(?:export\s+)?MODEL_PLATFORM_API_KEY=(.*)$", text, re.M)
    key = re.sub(r"\s+#.*$", "", matches[-1]).strip().strip("\"'") if matches else ""
    key = "".join(key.split())
    if not key:
        raise AuthError("No key in the legacy API-key file.")
    return key


def bound(value):
    if any(value.get(k) != v for k, v in BINDING.items()):
        raise AuthError("Authentication belongs to another platform or client. Run auth.sh login.")
    if not value.get("account", {}).get("id"):
        raise AuthError("Authentication has no account binding. Run auth.sh login.")


def token_document(tokens, account):
    if (tokens.get("token_type", "").lower() != "bearer"
            or not isinstance(tokens.get("access_token"), str)
            or not isinstance(tokens.get("refresh_token"), str)
            or set(tokens.get("scope", "").split()) != set(SCOPES.split())):
        raise AuthError("The platform returned invalid OAuth credentials. Run login again.")
    return {**BINDING, "mode": "oauth", "account": account,
            "access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
            "expires_at": time.time() + int(tokens["expires_in"]), "scope": tokens["scope"]}


def refresh(value):
    # Durable marker BEFORE sending: a killed process or uncertain network exchange must
    # never reuse a refresh token the server may already have consumed.
    pending = {**value, "needs_login": True}
    atomic_write(credential_path(), pending)
    try:
        tokens = request(ISSUER + "/api/oauth/token", {
            "grant_type": "refresh_token", "refresh_token": value["refresh_token"],
            "client_id": CLIENT, "resource": RESOURCE}, form=True)
        updated = token_document(tokens, value["account"])
        profile = rpc("get_profile", token=updated["access_token"])
        if profile.get("id") != value["account"]["id"]:
            raise AuthError("The refreshed connection changed accounts.")
        atomic_write(credential_path(), updated)
        return updated
    except (AuthError, KeyError, ValueError, OSError):
        raise AuthError("OAuth refresh could not be completed safely. Run auth.sh login again.") from None


def access_token(validate=False, rejected=None):
    with locked():
        value = load()
        if not value or value.get("mode") == "logged_out":
            return None
        bound(value)
        if value.get("mode") == "api_key":
            key = legacy_key()
            if rpc("get_profile", token=key).get("id") != value["account"]["id"]:
                raise AuthError("Legacy key changed accounts. Select legacy mode again explicitly.")
            return key
        if value.get("mode") != "oauth" or value.get("needs_login"):
            raise AuthError("OAuth needs login again. Run the installed auth.sh login command.")
        if (not isinstance(value.get("expires_at"), (int, float))
                or not isinstance(value.get("access_token"), str)
                or not isinstance(value.get("refresh_token"), str)):
            raise AuthError("OAuth credentials are incomplete. Run auth.sh login again.")
        if value.get("expires_at", 0) <= time.time() + 120 or rejected == value.get("access_token"):
            value = refresh(value)
        if validate:
            try:
                profile = rpc("get_profile", token=value["access_token"])
            except NetworkError:
                raise
            except Rejected:
                value = refresh(value)
                profile = value["account"]
            if profile.get("id") != value["account"]["id"]:
                raise AuthError("Connection changed accounts. Run login again.")
        return value["access_token"]


def call(name, arguments=None):
    token = access_token()
    try:
        return rpc(name, arguments, token)
    except NetworkError:
        raise
    except Rejected:
        # Retry exactly once. Another process may already have refreshed this token.
        if not token or load().get("mode") != "oauth":
            raise
        return rpc(name, arguments, access_token(rejected=token))


def partition():
    value = load()
    bound(value)
    return hashlib.sha256((RESOURCE + "\n" + value["account"]["id"]).encode()).hexdigest()[:24]


def login(timeout=300, no_browser=False):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    answer = {}
    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            valid = (parsed.path == "/callback" and query.get("state") == [state]
                     and query.get("iss") == [ISSUER]
                     and (len(query.get("code", [])) == 1 or len(query.get("error", [])) == 1))
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Return to your terminal. This window may be closed." if valid else b"Invalid OAuth callback.")
            if valid:
                answer.update(query)
    with http.server.HTTPServer(("127.0.0.1", 0), Callback) as listener:
        listener.timeout = 1
        redirect = "http://127.0.0.1:%d/callback" % listener.server_port
        url = ISSUER + "/api/oauth/authorize?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": CLIENT, "redirect_uri": redirect,
            "scope": SCOPES, "resource": RESOURCE, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        if no_browser:
            print("Open this consent page in your browser:\n" + url, flush=True)
        else:
            print("Opening the production consent page. Waiting for approval…", flush=True)
            def open_browser():
                if not webbrowser.open(url):
                    print("Open this consent page in your browser:\n" + url, flush=True)
            # Some browser launchers wait until their window closes. The callback
            # listener must already be servicing requests during that wait.
            threading.Thread(target=open_browser, daemon=True).start()
        deadline = time.monotonic() + timeout
        while not answer and time.monotonic() < deadline:
            listener.handle_request()
    if not answer or "error" in answer:
        raise AuthError("Login timed out or was declined. The existing connection is unchanged.")
    tokens = request(ISSUER + "/api/oauth/token", {
        "grant_type": "authorization_code", "code": answer["code"][0],
        "code_verifier": verifier, "redirect_uri": redirect, "client_id": CLIENT,
        "resource": RESOURCE}, form=True)
    account = rpc("get_profile", token=tokens.get("access_token"))
    value = token_document(tokens, account)
    with locked():
        atomic_write(credential_path(), value)
    print("Connected to production as " + (account.get("email") or account["id"]) + ". Reconnect MCP clients.")


def logout():
    with locked():
        value = load()
        if value.get("mode") == "oauth":
            bound(value)
            atomic_write(credential_path(), {**value, "needs_login": True})
            request(ISSUER + "/api/oauth/revoke", {
                "token": value["refresh_token"], "client_id": CLIENT}, form=True)
        atomic_write(credential_path(), {"mode": "logged_out"})
    print("Disconnected. Reconnect MCP clients to clear their cached headers.")


def main():
    parser = SafeParser(description="Novadde production authentication; never paste credentials into chat.")
    parser.add_argument("command", choices=["login", "logout", "status", "legacy-api-key", "headers", "call", "partition"])
    parser.add_argument("tool", nargs="?")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    try:
        if args.command == "login":
            login(args.timeout, args.no_browser)
        elif args.command == "logout":
            logout()
        elif args.command == "legacy-api-key":
            key = legacy_key()
            account = rpc("get_profile", token=key)
            with locked():
                atomic_write(credential_path(), {**BINDING, "mode": "api_key", "account": account})
            print("Explicit legacy API-key mode selected for " + (account.get("email") or account["id"]) + ".")
        elif args.command == "headers":
            token = access_token(validate=True)
            print(json.dumps({"Authorization": "Bearer " + token} if token else {}))
        elif args.command == "call":
            raw = sys.stdin.read() if not sys.stdin.isatty() else ""
            arguments = json.loads(raw) if raw.strip() else {}
            print(json.dumps(call(args.tool, arguments)))
        elif args.command == "partition":
            print(partition())
        else:
            token = access_token(validate=True)
            value = load()
            print("Platform: " + ISSUER)
            if not token:
                print("No connection. Run the installed auth.sh login command.")
                return 3
            print("Authentication: " + value["mode"])
            print("Account: " + (value["account"].get("email") or value["account"]["id"]))
        return 0
    except (AuthError, OSError, ValueError, KeyError):
        # Exception values can be hostile upstream data; expose only our own diagnostics.
        exc = sys.exc_info()[1]
        print(str(exc) if isinstance(exc, AuthError) else "Authentication could not be completed. Run login again.", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
