"""Tell the session when one of its GPU jobs finishes, so nothing has to poll for it.

This is the plugin's half of the control plane's `job_wakeup` sweep. A platform job takes minutes
to hours; an agent told to wait on it fills the context with identical snapshots until the
conversation dies of it. The fix is the same one the deployment made: the agent's turn ends at
`submit_job`, and something outside the conversation says when there is a result.

What is delivered is deliberately thin -- id, model, status -- and never the results. The agent
calls `get_job` if it wants them. That is where the context saving actually comes from.

Two rules carried over from the deployment, both learned the hard way there:

* A job already terminal on the first pass is recorded silently. Otherwise the first poll of a
  returning user announces their entire job history as notifications.
* Every job of the credential's account is watched, not only this session's, because that is the
  scope the platform's own `GET /api/jobs` has. Ids this session submitted are marked, so the
  distinction is visible without needing a second source of truth.

The key is read from ~/.config/geodesic/model-platform.env on every pass, not once at start. A
monitor starts with the session, and the setup the user follows -- mint a key, save it from their
own terminal -- very often happens during that session. A watcher that exited because there was
no key yet stayed gone until the next session, while everything else started working.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

TERMINAL = {"completed", "failed", "cancelled"}
PAGE_SIZE = 50
DEFAULT_INTERVAL = 45.0
#: Long enough that a transient outage does not hammer the platform, short enough that a fixed
#: one is picked up without restarting the session.
ERROR_BACKOFF = 300.0
#: The shell reader of the key, the one the hooks use. Asking it, rather than parsing the file a
#: second way here, keeps the watcher to the exact rules the MCP connection's headersHelper follows.
MP_AUTH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mp-auth.sh")


def read_key() -> str:
    """The key in the file right now, or '' when there is none or it cannot be read."""
    try:
        done = subprocess.run(
            ["bash", "-c", '. "$1" >/dev/null 2>&1; printf %s "$MP_KEY"', "mp-auth", MP_AUTH],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def say(line: str) -> None:
    """One line to stdout is one notification to Claude."""
    print(line, flush=True)


def fetch(url: str, key: str) -> list:
    request = urllib.request.Request(
        f"{url}/api/jobs?page_size={PAGE_SIZE}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    return jobs if isinstance(jobs, list) else []


def load(path: str) -> dict:
    try:
        with open(path) as handle:
            value = json.load(handle)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def store(path: str, value: dict) -> None:
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w") as handle:
            json.dump(value, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def main() -> int:
    url = (os.environ.get("MP_URL") or "").rstrip("/")
    data_dir = os.environ.get("NOVADDE_DATA") or ""
    if not url or not data_dir:
        return 0
    try:
        interval = float(os.environ.get("NOVADDE_WATCH_INTERVAL") or DEFAULT_INTERVAL)
    except ValueError:
        interval = DEFAULT_INTERVAL
    interval = max(15.0, interval)

    state_path = os.path.join(data_dir, "watch-state.json")
    session_path = os.path.join(data_dir, "session-jobs.json")
    seen = load(state_path)
    first_pass = not seen

    while True:
        key = read_key()
        if not key:
            # No credential is not an error: the plugin is usable read-only, and a watcher that
            # announced its own uselessness every session would be noise. It waits and looks at the
            # file again, and the first pass that has a key is still the silent first pass.
            time.sleep(interval)
            continue
        try:
            jobs = fetch(url, key)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                say(
                    "[novadde-job] The Model Platform refused this credential, so job "
                    "notifications are off until it is replaced. Tell the user to run "
                    "/novadde:setup; do not retry it yourself."
                )
                return 1
            time.sleep(ERROR_BACKOFF)
            continue
        except Exception:
            # A network blip must not end the watch, and must not be reported as news.
            time.sleep(ERROR_BACKOFF)
            continue

        mine = load(session_path)
        changed = False
        for job in jobs:
            if not isinstance(job, dict):
                continue
            job_id = job.get("id")
            status = (job.get("status") or "").lower()
            if not job_id or not status:
                continue
            was = seen.get(job_id)
            if was == status:
                continue
            seen[job_id] = status
            changed = True
            if status not in TERMINAL or first_pass or was in TERMINAL:
                continue
            here = " submitted in this session," if job_id in mine else ""
            say(
                f"[novadde-job] Job {job_id} ({job.get('model') or 'unknown model'}),{here} "
                f"finished: {status}. Report this to the user; call get_job for the details "
                f"rather than assuming them."
            )
        if changed:
            store(state_path, seen)
        first_pass = False
        time.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
