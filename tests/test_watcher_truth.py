"""The brief promises job notifications only where the watcher can deliver them.

The agent is told to end its turn at submit_job because something will report the result. In a
Claude Code session the only thing that can is the plugin's novadde-jobs monitor, and three sources
promised it whatever the session was:

* session-brief.sh said "a watcher polls your jobs ... so end the turn after submit_job" whenever
  the key file had a key. But Claude Code starts plugin monitors only in the interactive CLI, and
  skips them wherever the Monitor tool is unavailable: on Bedrock, Vertex and Foundry, and with
  DISABLE_TELEMETRY or CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC set (code.claude.com/docs/en/
  plugins-reference#monitors, /tools-reference#monitor-tool). A `claude -p` or Agent SDK session
  runs with CLAUDE_CODE_ENTRYPOINT=sdk-*, and a Claude Desktop session with claude-desktop; neither
  is the interactive CLI. Nor, by the CLI's own startup code, is a `claude -p` under the GitHub
  Action (claude-code-github-action) or Desktop's other session kind (local-agent). In all of
  those the agent ended its turn and nothing ever came back.
* The Model Platform's MCP server tells every client, in its instructions and in submit_job's and
  wait_for_job's descriptions, that "this deployment watches the job and wakes the conversation on
  its own" (served on prod today). That is the hosted deployment's job_wakeup sweep, which does
  not exist in Claude Code.
* prompt/mcp-brief.md, built into agents/novadde.md, said "this session watches the job and tells
  you" with no condition at all.

So the brief now always sets the server's claim aside, and then says exactly one of `Job
notifications: ON` or `Job notifications: OFF, because <reason>`, the second followed by what to do
instead: give the user the job's id, say nothing will report it, and check with get_job when asked.
ON needs a key in ~/.config/geodesic/model-platform.env -- the one store, and the one the watcher
reads -- that the platform did not refuse, and a session where Claude Code starts monitors. The
agent body and the README defer to that line, and are checked here, because the agent-file guard
only proves agents/novadde.md was built from prompt/, not that prompt/ is true. The two listings a
user reads before installing -- the plugin's manifest and its marketplace entry -- say the same.

Lines are compared whole, so a reworded promise cannot slip past a substring. Pipelines are off in
this release, so nothing here names them.

Written for the oldest python3 a Mac ships (3.9) as well as CI's.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import KEY, REPO, SCRIPTS, Checks, Sandbox, key_file  # noqa: E402

PLUGIN = os.path.join(REPO, "plugins", "novadde")
WATCH_JOBS = os.path.join(SCRIPTS, "lib", "watch_jobs.py")
SHOWN = "~/.config/geodesic/model-platform.env"
QUOTA_OK = {"GET /api/submission-quota": {
    "status": 200, "json": {"limit": 5, "used": 1, "remaining": 4,
                            "resetsAt": "2026-09-28T00:00:00Z"}}}
QUOTA_REFUSED = {"GET /api/submission-quota": {
    "status": 401, "json": {"detail": "Sign in or supply an API key."}}}

#: Said in every session, ON or OFF, because the server says the opposite in every session. Worded
#: as a condition, so it stays true once the platform stops making the claim.
OVERRIDE = (
    "If the model_platform server's own instructions or a tool's description say this deployment "
    "watches each job and wakes the conversation when it finishes, that describes the hosted "
    "NovaDDE deployment, not this session: here only the Job notifications line below says "
    "whether anything will."
)
ON = (
    "Job notifications: ON. A watcher polls your jobs in the background and will tell you when one "
    "reaches a terminal state, so end the turn after submit_job instead of waiting on it, and do "
    "not loop on wait_for_job."
)
OFF_AFTER = (
    "After submit_job, give the user the job's id, tell them you will not hear when it finishes, "
    "and offer to check on it later. When they ask, or at the start of your next turn, check it "
    "with get_job; do not end a turn expecting to be woken."
)
#: The two lines the brief used to print for any session with a key: the promise that must not
#: come back unearned. Whole lines, as the brief printed them.
OLD_PROMISE = [
    "A watcher polls your jobs in the background and will tell you when one reaches a terminal "
    "state,",
    "so end the turn after submit_job instead of waiting on it.",
]
NO_KEY = f"there is no key in {SHOWN} for the job watcher to read"
REFUSED = (f"the platform refused the key in {SHOWN}, and the job watcher stops at the first "
           "refusal")
DESKTOP = "this is a Claude Desktop session (claude-desktop), where plugin monitors do not run"
NON_INTERACTIVE = "this is a non-interactive session ({}), where plugin monitors do not run"

#: The agent body's unconditional promise, which no surface may make again.
OLD_BODY_PROMISE = ("The turn may end right after `submit_job`: this session watches the job and "
                    "tells you")
#: What the agent body says instead: the session brief's line decides, and without it, nothing will.
BODY_DEFERS = ("Whether the turn may end right after `submit_job` is decided per session, by the "
               "\"Job notifications\" line of the `<NOVADDE_SESSION>` block.")
BODY_OFF = ("When it says OFF, or there is no such line, nothing will: give the user the job's id, "
            "say you will not hear when it finishes, and check it with `get_job` when they ask.")
OLD_README_PROMISE = "A background watcher polls your jobs and tells Claude when one finishes"
README_CONDITION = ("In the interactive CLI, once the key is saved in "
                    "`~/.config/geodesic/model-platform.env`, a background watcher polls your jobs")
README_OFF = ("Where Claude Code runs no plugin monitors (Claude Desktop, `claude -p`, the Agent "
              "SDK, the GitHub Action, Bedrock, Vertex, Foundry, or with `DISABLE_TELEMETRY` or "
              "`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` set), and when the key is missing or the "
              "platform refuses it, the session brief says notifications are off")
#: What each listing said before, unqualified, and the condition it must carry now. "in the
#: interactive CLI" is the text that tells the two apart; the feature names survive in both.
LISTINGS_OLD = {
    "plugin.json": "and a watcher that tells you when a job finishes",
    "marketplace.json": "science skills, job notifications.",
}
LISTING_CONDITION = "in the interactive CLI"


def flat(path):
    """The file's text with line wrapping undone, so a sentence is found whatever its breaks."""
    with open(path, encoding="utf-8") as handle:
        return " ".join(handle.read().split())


def off(reason):
    return [
        f"Job notifications: OFF, because {reason}. Nothing will tell you when a job finishes, "
        "and nothing will wake this conversation.",
        OFF_AFTER,
    ]


def brief(box, **env):
    """The lines of session-brief.sh's additionalContext, run as the SessionStart hook is."""
    result = box.run_with("session-brief.sh", env, stdin=json.dumps({"cwd": "/work"}))
    try:
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return []
    return context.splitlines()


def notice(lines):
    """From the Job notifications line to the end of what it says, nothing else."""
    for i, line in enumerate(lines):
        if line.startswith("Job notifications:"):
            return lines[i:i + (2 if line.startswith("Job notifications: OFF") else 1)]
    return []


def notification_lines(lines):
    return [line for line in lines if line.startswith("Job notifications:")]


def old_promise_made(lines):
    return [line for line in OLD_PROMISE if line in lines]


def line_after(lines, line):
    """The line that follows `line`, or '' when it is absent or last."""
    if line not in lines:
        return ""
    i = lines.index(line)
    return lines[i + 1] if i + 1 < len(lines) else ""


class Box(Sandbox):
    """The harness sandbox, with a run that adds variables for one call only."""

    def run_with(self, script, extra, stdin=""):
        saved = dict(self.env)
        self.env.update(extra)
        try:
            return self.run(script, stdin=stdin)
        finally:
            self.env.clear()
            self.env.update(saved)


def ran(lines):
    """Whether the hook printed its brief at all (it arrives wrapped in <NOVADDE_SESSION>)."""
    return any(line.startswith("Working directory for this session") for line in lines)


def test_no_key_in_the_file_turns_notifications_off(checks):
    print("no key in the file: the watcher has nothing to read")
    with Box(QUOTA_OK, key=None) as box:
        checks.eq("(precondition) the key file does not exist", os.path.exists(box.env_file), False)
        lines = brief(box)
        checks.eq("(precondition) the brief ran", ran(lines), True)
        checks.eq("no file: notifications are OFF, and why", notice(lines), off(NO_KEY))
        checks.eq("no file: exactly one Job notifications line", len(notification_lines(lines)), 1)
    with Box(QUOTA_OK, key=None) as box:
        os.makedirs(os.path.dirname(box.env_file))
        with open(box.env_file, "w") as handle:
            handle.write("MODEL_PLATFORM_URL=https://platform.test\n")
        lines = brief(box)
        checks.eq("a readable file holding only a URL line is still OFF", notice(lines),
                  off(NO_KEY))


def watcher_on_a_refused_key():
    """(what it returned, what it said) when the platform answers the watcher's first poll 401."""
    spec = importlib.util.spec_from_file_location("watch_jobs_under_test", WATCH_JOBS)
    watcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watcher)

    class Stop(Exception):
        pass

    def fetch(url, key):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    def sleep(_seconds):
        raise Stop

    watcher.fetch = fetch
    watcher.time = types.SimpleNamespace(sleep=sleep)
    home = tempfile.mkdtemp(prefix="novadde-refused-")
    os.makedirs(os.path.dirname(key_file(home)))
    with open(key_file(home), "w") as handle:
        handle.write(f"MODEL_PLATFORM_API_KEY={KEY}\n")
    saved_env = dict(os.environ)
    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
    os.environ.update(HOME=home, MP_URL="https://dev-platform.geodesiclab.org",
                      NOVADDE_DATA=os.path.join(home, "data"))
    said = io.StringIO()
    try:
        with contextlib.redirect_stdout(said):
            try:
                outcome = watcher.main()
            except Stop:
                outcome = "still watching"
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        shutil.rmtree(home, ignore_errors=True)
    return outcome, said.getvalue()


def test_a_refused_key_turns_notifications_off(checks):
    print("a key the platform refuses")
    outcome, said = watcher_on_a_refused_key()
    # What makes OFF the true answer: the watcher gives up at the first refusal. If it ever keeps
    # polling instead, this goes red, and the brief's reason has to change with it.
    checks.eq("(precondition) the watcher exits at the first 401", outcome, 1)
    checks.eq("(precondition) after saying the credential was refused",
              "refused this credential" in said, True)
    with Box(QUOTA_REFUSED) as box:
        lines = brief(box)
        checks.eq("(precondition) the brief says the platform REFUSED the key",
                  any(f"REFUSED the key in {SHOWN}" in line for line in lines), True)
        checks.eq("a refused key: notifications are OFF, and why", notice(lines), off(REFUSED))


def test_a_key_in_an_interactive_cli_session_turns_notifications_on(checks):
    print("a key in the file, an interactive CLI session")
    for label, env in (("no entrypoint set", {}), ("CLAUDE_CODE_ENTRYPOINT=cli",
                                                   {"CLAUDE_CODE_ENTRYPOINT": "cli"})):
        with Box(QUOTA_OK) as box:
            lines = brief(box, **env)
            checks.eq(f"{label}: (precondition) the brief is credentialed",
                      any("credentialed as mp_tes...cdef." in line for line in lines), True)
            checks.eq(f"{label}: notifications are ON", notice(lines), [ON])
            checks.eq(f"{label}: exactly one Job notifications line",
                      len(notification_lines(lines)), 1)
            checks.eq(f"{label}: the old two-line promise is gone", old_promise_made(lines), [])
    with Box(QUOTA_OK) as box:
        checks.eq("CLAUDE_CODE_USE_BEDROCK=0 does not turn it off",
                  notice(brief(box, CLAUDE_CODE_USE_BEDROCK="0")), [ON])


def test_sessions_that_start_no_monitors_turn_notifications_off(checks):
    print("a key in the file, but Claude Code will not start the monitor")
    cannot = "this Claude Code session cannot run plugin monitors ({} is set)"
    cases = [
        ({"CLAUDE_CODE_USE_BEDROCK": "1"}, cannot.format("CLAUDE_CODE_USE_BEDROCK")),
        ({"CLAUDE_CODE_USE_VERTEX": "true"}, cannot.format("CLAUDE_CODE_USE_VERTEX")),
        ({"CLAUDE_CODE_USE_FOUNDRY": "1"}, cannot.format("CLAUDE_CODE_USE_FOUNDRY")),
        # Documented: any value at all, "0" included, disables the Monitor tool.
        ({"DISABLE_TELEMETRY": "0"}, cannot.format("DISABLE_TELEMETRY")),
        ({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
         cannot.format("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"},
         "this is a non-interactive session (sdk-cli), where plugin monitors do not run"),
        ({"CLAUDE_CODE_ENTRYPOINT": "sdk-ts"},
         "this is a non-interactive session (sdk-ts), where plugin monitors do not run"),
        # The CLI names a `claude -p` run claude-code-github-action instead of sdk-cli when
        # CLAUDE_CODE_ACTION is set, as the GitHub Action sets it; it is still a -p run.
        ({"CLAUDE_CODE_ENTRYPOINT": "claude-code-github-action"},
         NON_INTERACTIVE.format("claude-code-github-action")),
    ]
    for env, reason in cases:
        with Box(QUOTA_OK) as box:
            lines = brief(box, **env)
            checks.eq(f"OFF under {env}", notice(lines), off(reason))
            checks.eq(f"and no old promise under {env}", old_promise_made(lines), [])


def test_desktop_entrypoint_turns_notifications_off(checks):
    print("a Claude Desktop session (CLAUDE_CODE_ENTRYPOINT=claude-desktop)")
    with Box(QUOTA_OK) as box:
        # The same box without the entrypoint is ON, so what turns it off below is the entrypoint
        # alone, not the key or the platform's answer.
        checks.eq("(precondition) this box is ON without the entrypoint", notice(brief(box)), [ON])
        lines = brief(box, CLAUDE_CODE_ENTRYPOINT="claude-desktop")
        checks.eq("(precondition) the brief is credentialed",
                  any("credentialed as mp_tes...cdef." in line for line in lines), True)
        checks.eq("Desktop: the watcher is not promised, in the old words or the new",
                  (old_promise_made(lines), ON in lines), ([], False))
        checks.eq("Desktop: notifications are OFF, and why", notice(lines), off(DESKTOP))
    # The other values Claude Desktop starts the CLI with. local-agent is not a claude-desktop*
    # value, so it needs its own case; claude-desktop-3p is here so the glob stays a glob.
    for value in ("local-agent", "claude-desktop-3p"):
        with Box(QUOTA_OK) as box:
            lines = brief(box, CLAUDE_CODE_ENTRYPOINT=value)
            checks.eq(f"{value}: (precondition) the brief is credentialed",
                      any("credentialed as mp_tes...cdef." in line for line in lines), True)
            checks.eq(f"{value}: notifications are OFF, and why", notice(lines),
                      off(f"this is a Claude Desktop session ({value}), where plugin monitors do "
                          "not run"))


def test_the_servers_wake_up_claim_is_set_aside_in_every_session(checks):
    print("the platform's own wake-up claim")
    for label, routes, key, env in (
            ("ON", QUOTA_OK, KEY, {}),
            ("OFF for no key", QUOTA_OK, None, {}),
            ("OFF for a refused key", QUOTA_REFUSED, KEY, {}),
            ("OFF for Desktop", QUOTA_OK, KEY, {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"})):
        with Box(routes, key=key) as box:
            lines = brief(box, **env)
            checks.eq(f"{label}: the override is said once, just before the Job notifications line",
                      (lines.count(OVERRIDE), line_after(lines, OVERRIDE)[:18]),
                      (1, "Job notifications:"))


def test_the_agent_body_and_the_readme_defer_to_that_line(checks):
    print("prompt/mcp-brief.md, agents/novadde.md and the README")
    brief_src = flat(os.path.join(PLUGIN, "prompt", "mcp-brief.md"))
    agent = flat(os.path.join(PLUGIN, "agents", "novadde.md"))
    checks.eq("(precondition) the agent file carries the MCP brief",
              "## Structural biology on this deployment" in agent, True)
    checks.eq("mcp-brief.md defers to the Job notifications line", BODY_DEFERS in brief_src, True)
    checks.eq("and says what to do when it is OFF or missing", BODY_OFF in brief_src, True)
    checks.eq("and the built agent says both",
              (BODY_DEFERS in agent, BODY_OFF in agent), (True, True))
    checks.eq("no surface promises the watcher unconditionally",
              [name for name, text in (("mcp-brief.md", brief_src), ("agents/novadde.md", agent))
               if OLD_BODY_PROMISE in text], [])
    readme = flat(os.path.join(REPO, "README.md"))
    checks.eq("README no longer promises notifications unconditionally",
              OLD_README_PROMISE in readme, False)
    checks.eq("README names where they arrive, and where they do not",
              (README_CONDITION in readme, README_OFF in readme), (True, True))


def listing_descriptions():
    """{listing: description} for the two texts a user reads before installing the plugin."""
    with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as handle:
        plugin = json.load(handle)
    with open(os.path.join(REPO, ".claude-plugin", "marketplace.json"), encoding="utf-8") as handle:
        entries = [entry for entry in json.load(handle).get("plugins", [])
                   if entry.get("name") == "novadde"]
    return {"plugin.json": plugin.get("description", ""),
            "marketplace.json": entries[0].get("description", "") if entries else ""}


def test_the_plugin_listings_promise_notifications_only_in_the_interactive_cli(checks):
    print("the plugin's manifest and its marketplace entry")
    listings = listing_descriptions()
    # Both still offer the feature, so the condition below is checked on a sentence that names it,
    # not passed by a listing that dropped the subject.
    checks.eq("(precondition) both listings name the watcher or job notifications",
              sorted(name for name, text in listings.items()
                     if "watcher" in text or "job notifications" in text),
              ["marketplace.json", "plugin.json"])
    checks.eq("neither listing keeps its unconditional wording",
              sorted(name for name, text in listings.items() if LISTINGS_OLD[name] in text), [])
    checks.eq("both say notifications come in the interactive CLI",
              sorted(name for name, text in listings.items() if LISTING_CONDITION not in text), [])


def main():
    checks = Checks("test_watcher_truth")
    test_no_key_in_the_file_turns_notifications_off(checks)
    test_a_refused_key_turns_notifications_off(checks)
    test_a_key_in_an_interactive_cli_session_turns_notifications_on(checks)
    test_sessions_that_start_no_monitors_turn_notifications_off(checks)
    test_desktop_entrypoint_turns_notifications_off(checks)
    test_the_servers_wake_up_claim_is_set_aside_in_every_session(checks)
    test_the_agent_body_and_the_readme_defer_to_that_line(checks)
    test_the_plugin_listings_promise_notifications_only_in_the_interactive_cli(checks)
    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
