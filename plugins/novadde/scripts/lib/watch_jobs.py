"""Claude interactive notifications using the plugin's shared MCP OAuth connection."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import sys
import time

import oauth_client as auth

TERMINAL = {"completed", "partial", "failed", "cancelled"}
DEFAULT_INTERVAL = 45.0
ERROR_BACKOFF = 300.0


def load(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def connection_dir():
    base = os.environ.get("NOVADDE_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA") or str(Path.home() / ".cache/novadde")
    return Path(base) / "connections" / auth.partition()


def collect(seen, token=None):
    def call(name, arguments):
        return auth.rpc(name, arguments, token) if token else auth.call(name, arguments)
    jobs = call("list_jobs", {"limit": 200}).get("jobs", [])
    runs = call("list_pipeline_runs", {"limit": 200}).get("runs", [])
    current = {item["id"]: item for item in jobs + runs if isinstance(item, dict) and item.get("id")}
    # The listing is bounded: keep watching older jobs that were already active.
    for ident, status in seen.items():
        if status not in TERMINAL and ident not in current:
            name = "get_pipeline_run" if ident.startswith("run-") else "get_job"
            key = "run_id" if ident.startswith("run-") else "job_id"
            try:
                current[ident] = call(name, {key: ident})
            except auth.NetworkError:
                raise
            except auth.AuthError:
                # Deleted jobs are not completion notices; credentials are checked below.
                auth.access_token(validate=True)
    return list(current.values())


def poll():
    # Validate on each pass so revoked credentials and replaced legacy accounts stop notices.
    token = auth.access_token(validate=True)
    if not token:
        raise auth.AuthError("No OAuth connection. Run /novadde:setup.")
    value = auth.load()
    if value.get("mode") == "oauth" and value.get("access_token") != token:
        raise auth.AuthError("Connection changed during the poll. Reconnecting.")
    path = connection_dir()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(path / "watch-state.lock", "a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        seen = load(path / "watch-state.json")
        mine = load(path / "session-jobs.json")
        initial = not seen
        notices = []
        for job in collect(seen, token):
            ident, status = job.get("id"), (job.get("status") or "").lower()
            if not ident or not status or seen.get(ident) == status:
                continue
            was = seen.get(ident)
            seen[ident] = status
            if status not in TERMINAL or initial or was in TERMINAL:
                continue
            here = " submitted in this session," if ident in mine else ""
            notices.append("[novadde-job] Job %s (%s),%s finished: %s. Report this to the user; call %s for details." % (
                ident, job.get("model") or job.get("pipeline") or "unknown model", here, status,
                "get_pipeline_run" if ident.startswith("run-") else "get_job"))
        if connection_dir() != path:
            raise auth.AuthError("Account changed during the poll. Reconnecting.")
        # Commit deduplication while locked, before emitting any notification.
        auth.atomic_write(path / "watch-state.json", seen)
        for notice in notices:
            print(notice, flush=True)
    return len(notices)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="one real MCP poll, for release verification")
    args = parser.parse_args()
    interval = max(15.0, float(os.environ.get("NOVADDE_WATCH_INTERVAL") or DEFAULT_INTERVAL))
    refused = False
    while True:
        try:
            poll()
            refused = False
        except auth.NetworkError:
            if args.once:
                print("Watcher could not reach production.", file=sys.stderr)
                return 2
            time.sleep(ERROR_BACKOFF)
            continue
        except auth.AuthError:
            if args.once:
                print("Watcher needs authentication. Run /novadde:setup.", file=sys.stderr)
                return 3
            if not refused:
                print("[novadde-job] Notifications paused: reconnect with /novadde:setup. The watcher will resume after login.", flush=True)
            refused = True
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
