"""The Model Platform key lives in one 0600 file, and nowhere else.

The file is ~/.config/geodesic/model-platform.env, with a line MODEL_PLATFORM_API_KEY=mp_...

Before this, the key had two homes. The MCP server authenticated with a `sensitive` plugin option,
kept in the OS keychain and substituted into `.mcp.json` as `${user_config.api_key}`; the job
watcher, which as a monitor is given no plugin options at all, read the file. A user who filled in
one and not the other got half a session -- tools with no notifications, or a SessionStart brief
promising a watcher that had exited at start for want of a key. And the file's
`MODEL_PLATFORM_URL` line, which on lab Macs points at an internal address, moved the hooks and the
watcher -- key and all -- to a host the MCP server never talks to.

Now every reader takes the key from that one file, and the platform is one literal:

* the MCP connection, through a `headersHelper` in `.mcp.json`: an inline `sh` string that prints
  `{"Authorization":"Bearer <key>"}`, or `{}` when there is none. Claude Code runs it and sends
  what it prints; when the string is broken it connects anonymously and says nothing, so the string
  is executed here, on every hand-edit of the file seen in the wild (a leading `export `, quotes,
  CRLF, a trailing comment, an old line left above a new one);
* the hooks and the setup check, through `scripts/mp-auth.sh`, with the same pipeline -- held to
  the helper's answer case by case, so the two cannot drift;
* the job watcher, which now re-reads the file on every pass instead of exiting when a session
  starts without a key, so a key saved mid-session turns notifications on.

The setup skill and the README say how to put the key there: minted at the platform's API Keys page
and saved from the user's own terminal by a one-liner that reads it hidden. That one-liner is run
here too, because it is the only way the file gets written.

Written for the oldest python3 a Mac ships (3.9) as well as CI's.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import KEY, REPO, SCRIPTS, Checks, Sandbox, key_file  # noqa: E402

PLUGIN = os.path.join(REPO, "plugins", "novadde")
MCP_JSON = os.path.join(PLUGIN, ".mcp.json")
PLUGIN_JSON = os.path.join(PLUGIN, ".claude-plugin", "plugin.json")
SETUP_SKILL = os.path.join(PLUGIN, "skills", "setup", "SKILL.md")
README = os.path.join(REPO, "README.md")
MP_AUTH = os.path.join(SCRIPTS, "mp-auth.sh")
WATCH_JOBS = os.path.join(SCRIPTS, "lib", "watch_jobs.py")

PLATFORM = "https://dev-platform.geodesiclab.org"
# Stands in for the internal address a lab Mac's file carries. A reserved name (RFC 2606) rather
# than the real host, because this repo is read outside the lab and every check here needs only a
# URL that is not the platform's.
LAB_URL = "http://model-platform.lab.invalid:8000"
SHOWN = "~/.config/geodesic/model-platform.env"
NO_KEY_SENTENCE = "no key in ~/.config/geodesic/model-platform.env; run /novadde:setup"
BEARER = '{"Authorization":"Bearer mp_x"}'
# The keys the Claude Code MCP loader keeps a remote server with. Anything else -- a Codex-style
# `tools` table, say -- makes it drop the whole server, while `claude plugin validate --strict`
# still passes the file.
CLAUDE_SERVER_KEYS = {"type", "url", "headers", "headersHelper"}
# The option names the old two-store design read, and the variable that pointed the scripts at a
# second file. Pinned whole, so a script that reads any of them again is found by name.
RETIRED_READERS = ("CLAUDE_PLUGIN_OPTION_API_KEY", "CLAUDE_PLUGIN_OPTION_PLATFORM_URL",
                   "MODEL_PLATFORM_ENV_FILE")

# Every file below must give exactly the key mp_x. (label, file contents)
KEY_CASES = [
    ("a plain value", "MODEL_PLATFORM_API_KEY=mp_x\n"),
    ("a double-quoted value", 'MODEL_PLATFORM_API_KEY="mp_x"\n'),
    ("a single-quoted value", "MODEL_PLATFORM_API_KEY='mp_x'\n"),
    ("an `export ` line", "export MODEL_PLATFORM_API_KEY=mp_x\n"),
    ("an indented `export` with two spaces and a quoted value",
     '  export  MODEL_PLATFORM_API_KEY="mp_x"\n'),
    ("CRLF line endings", "MODEL_PLATFORM_URL=%s\r\nMODEL_PLATFORM_API_KEY=mp_x\r\n" % LAB_URL),
    ("a trailing comment", "MODEL_PLATFORM_API_KEY=mp_x # minted 2026-09-27\n"),
    ("a quoted value, then a comment", "MODEL_PLATFORM_API_KEY='mp_x'  # the lab key\n"),
    ("a trailing space", "MODEL_PLATFORM_API_KEY=mp_x \n"),
    ("a trailing tab", "MODEL_PLATFORM_API_KEY=mp_x\t\n"),
    ("an old `export` line, then a newer plain one",
     "export MODEL_PLATFORM_API_KEY=mp_old\nMODEL_PLATFORM_API_KEY=mp_x\n"),
    ("a lab Mac's file: the URL line, then the key",
     "MODEL_PLATFORM_URL=%s\nMODEL_PLATFORM_API_KEY=mp_x\n" % LAB_URL),
    ("no newline at the end", "MODEL_PLATFORM_API_KEY=mp_x"),
]
# Every one of these must give no key at all. (label, file contents, or None for no file)
NO_KEY_CASES = [
    ("no file", None),
    ("a file with no key line", "MODEL_PLATFORM_URL=%s\n" % LAB_URL),
    ("a commented-out key", "# MODEL_PLATFORM_API_KEY=mp_x\n"),
    ("an empty assignment", "MODEL_PLATFORM_API_KEY=\n"),
]


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write_key_file(home, text):
    """Write the credential file under HOME byte for byte (CRLF kept), or remove it for None."""
    path = key_file(home)
    if text is None:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-8"))


def mcp_server():
    """.mcp.json's `model_platform` entry, or {}."""
    servers = json.loads(read(MCP_JSON)).get("mcpServers") or {}
    return servers.get("model_platform") or {}


def headers_helper():
    """The inline sh string Claude Code runs for the MCP connection's headers, or None."""
    helper = mcp_server().get("headersHelper")
    return helper if isinstance(helper, str) and helper.strip() else None


def run_helper(helper, home):
    """Run the helper as the host does, with sh. Bytes, so a stray CR stays visible."""
    return subprocess.run(["sh", "-c", helper], env={"HOME": home, "PATH": "/usr/bin:/bin"},
                          capture_output=True, timeout=20)


def hooks_view(home, extra_env=None):
    """(MP_URL, MP_KEY) as scripts/mp-auth.sh sets them for every hook and for the watcher."""
    env = {"HOME": home, "PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_DATA": os.path.join(home, "data")}
    env.update(extra_env or {})
    done = subprocess.run(["bash", "-c", '. "$1"; printf "%s\\n%s" "$MP_URL" "$MP_KEY"', "t", MP_AUTH],
                          env=env, capture_output=True, timeout=20)
    url, _, key = done.stdout.decode("utf-8", "replace").partition("\n")
    return url, key


def bearer_of(stdout):
    """The key in a helper's output, '' for {}, or None when it is not the shape the host wants."""
    try:
        value = json.loads(stdout.decode("utf-8"))
    except ValueError:
        return None
    if value == {}:
        return ""
    header = value.get("Authorization", "") if isinstance(value, dict) else ""
    return header[len("Bearer "):] if header.startswith("Bearer ") else None


def brief(box, **extra_env):
    """The additionalContext session-brief.sh hands the agent."""
    env = dict(box.env, **extra_env)
    done = subprocess.run(["bash", os.path.join(SCRIPTS, "session-brief.sh")],
                          input=json.dumps({"cwd": "/work"}), env=env,
                          capture_output=True, text=True, timeout=60)
    try:
        return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return ""


def run_script(box, script, *args, **extra_env):
    env = dict(box.env, **extra_env)
    return subprocess.run(["bash", os.path.join(SCRIPTS, script), *args], env=env,
                          capture_output=True, text=True, timeout=60)


def fenced_blocks(text, lang="bash"):
    """The bodies of ```<lang> blocks, dedented, so one inside a list item compares as written."""
    blocks, body, inside = [], [], False
    for line in text.splitlines():
        if not inside and line.strip() == "```" + lang:
            inside, body = True, []
        elif inside and line.strip() == "```":
            blocks.append(textwrap.dedent("\n".join(body)) + "\n")
            inside = False
        elif inside:
            body.append(line)
    return blocks


def saving_one_liners(text):
    """The fenced blocks that save the key: the ones that read it with `read -rsp`."""
    return [block for block in fenced_blocks(text) if "read -rsp" in block]


def test_headers_helper_prints_the_key_from_the_file(checks):
    print("the headersHelper in .mcp.json, run with sh under a fake HOME")
    helper = headers_helper()
    checks.eq("(precondition) .mcp.json's model_platform has a headersHelper string",
              helper is not None, True)
    if helper is None:
        return
    home = tempfile.mkdtemp(prefix="novadde-helper-")
    try:
        for label, text in KEY_CASES:
            write_key_file(home, text)
            done = run_helper(helper, home)
            checks.eq(f"{label}: prints exactly {BEARER}", done.stdout, BEARER.encode())
            checks.eq(f"{label}: which is JSON with that one header",
                      bearer_of(done.stdout), "mp_x")
            checks.eq(f"{label}: nothing on stderr, exit 0", (done.stderr, done.returncode), (b"", 0))
        for label, text in NO_KEY_CASES:
            write_key_file(home, text)
            done = run_helper(helper, home)
            checks.eq(f"{label}: prints {{}}", done.stdout, b"{}")
            checks.eq(f"{label}: nothing on stderr, exit 0", (done.stderr, done.returncode), (b"", 0))
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_the_hooks_and_the_helper_read_the_same_key(checks):
    print("scripts/mp-auth.sh agrees with the headersHelper on every file")
    helper = headers_helper()
    checks.eq("(precondition) there is a helper to agree with", helper is not None, True)
    if helper is None:
        return
    home = tempfile.mkdtemp(prefix="novadde-agree-")
    try:
        for label, text in KEY_CASES + NO_KEY_CASES:
            write_key_file(home, text)
            from_helper = bearer_of(run_helper(helper, home).stdout)
            _, from_hooks = hooks_view(home)
            checks.eq(f"{label}: the hooks' MP_KEY is the helper's bearer ({from_helper!r})",
                      from_hooks, from_helper)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_mcp_json_carries_no_user_config_and_no_static_authorization(checks):
    print(".mcp.json")
    raw = read(MCP_JSON)
    servers = json.loads(raw).get("mcpServers") or {}
    checks.eq("(precondition) the server is still model_platform, the name the hook matchers match",
              sorted(servers), ["model_platform"])
    server = mcp_server()
    checks.eq("no ${user_config.…} anywhere in it", "${user_config" in raw, False)
    # The helper tests above run the string with sh directly, but Claude Code first expands every
    # ${NAME} and ${NAME:-default} in a plugin's headersHelper from its own environment (bare $NAME
    # and $(...) are left alone; read from Claude Code 2.1.267's plugin MCP loader). A ${f} or ${k}
    # would be the host's variable, or a "missing environment variable" config error, rather than
    # the helper's, and the connection would stop reading the file while those tests stayed green.
    helper = server.get("headersHelper")
    checks.eq("the headersHelper writes its variables bare ($HOME, $f, $k), never as ${…}, "
              "which the host would expand before sh runs it",
              isinstance(helper, str) and "${" not in helper, True)
    checks.eq("no static Authorization header",
              [name for name in (server.get("headers") or {}) if name.lower() == "authorization"], [])
    checks.eq("the url is the platform's endpoint, literally", server.get("url"), PLATFORM + "/api/mcp")
    checks.eq("the type is http", server.get("type"), "http")
    checks.eq("the server carries no key outside type, url, headers and headersHelper",
              sorted(set(server) - CLAUDE_SERVER_KEYS), [])


def test_plugin_json_has_no_api_key_or_platform_url_option(checks):
    print(".claude-plugin/plugin.json")
    options = json.loads(read(PLUGIN_JSON)).get("userConfig") or {}
    checks.eq("(precondition) the options that stay are still there",
              sorted(name for name in ("read_only", "user_message_suffix") if name in options),
              ["read_only", "user_message_suffix"])
    checks.eq("no api_key and no platform_url option",
              sorted(name for name in ("api_key", "platform_url") if name in options), [])
    checks.eq("no option is kept in the keychain",
              sorted(name for name, spec in options.items()
                     if isinstance(spec, dict) and spec.get("sensitive")), [])


def test_the_lab_url_line_does_not_move_the_platform(checks):
    print("a lab Mac's MODEL_PLATFORM_URL line")
    lab_file = "MODEL_PLATFORM_URL=%s\nMODEL_PLATFORM_API_KEY=%s\n" % (LAB_URL, KEY)
    quota = {"status": 200, "json": {"limit": 5, "used": 1, "remaining": 4,
                                     "resetsAt": "2026-09-28T00:00:00Z"}}
    with Sandbox({"GET /api/submission-quota": quota}, key=None) as box:
        write_key_file(box.root, lab_file)
        # A 0.1.0 install may still hand the hooks its old origin option; it must not count either.
        stale = {"CLAUDE_PLUGIN_OPTION_PLATFORM_URL": LAB_URL}
        url, key = hooks_view(box.root, stale)
        checks.eq("(precondition) the key on the next line is still read", key, KEY)
        checks.eq("the hooks' MP_URL is the platform", url, PLATFORM)
        context = brief(box, **stale)
        checks.eq("the brief names the platform",
                  "Model Platform: %s, credentialed as" % PLATFORM in context, True)
        checks.eq("and never the lab address", LAB_URL in context, False)
        status = run_script(box, "status.sh", **stale)
        checks.eq("/novadde:status names the platform",
                  status.stdout.splitlines()[:1], ["Platform      %s" % PLATFORM])


def test_the_brief_reads_the_file_not_the_option(checks):
    print("the SessionStart brief, and the other readers, take the key from the file only")
    quota = {"status": 200, "json": {"limit": 5, "used": 1, "remaining": 4,
                                     "resetsAt": "2026-09-28T00:00:00Z"}}
    elsewhere_key = "mp_elsewhere_0123456789ab"
    with Sandbox({"GET /api/submission-quota": quota,
                  "GET /api/auth/me": {"status": 200, "json": {"id": "u1"}}}, key=None) as box:
        # What a 0.1.0 install that kept its key only in the keychain looks like after the
        # upgrade: the option may still arrive, and the old override may still be exported.
        elsewhere = os.path.join(box.root, "elsewhere.env")
        with open(elsewhere, "w") as handle:
            handle.write(f"MODEL_PLATFORM_API_KEY={elsewhere_key}\n")
        stale = {"CLAUDE_PLUGIN_OPTION_API_KEY": "mp_from_the_keychain_0123",
                 "MODEL_PLATFORM_ENV_FILE": elsewhere}
        checks.eq("(precondition) the file under HOME does not exist",
                  os.path.exists(box.env_file), False)
        context = brief(box, **stale)
        checks.eq("(precondition) the brief ran", "Working directory for this session" in context, True)
        checks.eq("the brief says NO credential", "NO credential" in context, True)
        checks.eq(f"and says {NO_KEY_SENTENCE!r}", NO_KEY_SENTENCE in context, True)
        checks.eq("and claims no credential", "credentialed" in context, False)
        checks.eq("and sent no key to the platform",
                  [c for c in box.calls() if c["path"] == "/api/submission-quota"], [])
        status = run_script(box, "status.sh", **stale)
        checks.eq("/novadde:status says NONE and names the file",
                  [line for line in status.stdout.splitlines() if line.startswith("Credential")],
                  ["Credential    NONE: no key in %s. Run /novadde:setup." % SHOWN])
        check = run_script(box, "setup-credential.sh", "--check", **stale)
        checks.eq("setup-credential.sh --check finds nothing configured (exit 3)", check.returncode, 3)
        checks.eq("and verified nothing with the platform",
                  [c for c in box.calls() if c["path"] == "/api/auth/me"], [])

    # The same session with the key saved in the file: credentialed, from the file, by hint only.
    with Sandbox({"GET /api/submission-quota": quota,
                  "GET /api/auth/me": {"status": 200, "json": {"id": "u1"}}}) as box:
        hint = KEY[:6] + "..." + KEY[-4:]
        context = brief(box)
        checks.eq("with the key in the file, the brief is credentialed by its hint",
                  "credentialed as %s" % hint in context, True)
        checks.eq("and never carries the key itself", KEY in context, False)
        checks.eq("(precondition) and asked the platform for the allowance with it",
                  len([c for c in box.calls() if c["path"] == "/api/submission-quota"]), 1)
        check = run_script(box, "setup-credential.sh", "--check")
        checks.eq("setup-credential.sh --check says where the key came from",
                  [line for line in check.stdout.splitlines() if line.startswith("Credential")],
                  ["Credential: %s from %s" % (hint, SHOWN)])

    # A refused key is not a missing one: the fix is a new key, not a first one.
    refused = {"status": 401, "json": {"detail": "Sign in or supply an API key."}}
    with Sandbox({"GET /api/submission-quota": refused}) as box:
        context = brief(box)
        checks.eq("a refused key: the brief says the platform REFUSED the key in the file",
                  "REFUSED the key in %s" % SHOWN in context, True)
        checks.eq("a refused key: and names the status", "HTTP 401" in context, True)
        checks.eq("a refused key: and does not call it missing", "no key in" in context, False)
        checks.eq("a refused key: nor credentialed", "credentialed as" in context, False)
        checks.eq("a refused key: and never carries the key itself", KEY in context, False)

    # No script reads the retired stores. Pinned by the exact names, over every script shipped.
    scripts = sorted(os.path.join(folder, name)
                     for folder, _, names in os.walk(SCRIPTS) for name in names
                     if name.endswith((".sh", ".py")))
    checks.eq("(precondition) the scan reads mp-auth.sh and watch_jobs.py",
              {MP_AUTH, WATCH_JOBS} <= set(scripts), True)
    checks.eq("no script names the retired option variables or the file override",
              sorted("%s: %s" % (os.path.relpath(path, REPO), name)
                     for path in scripts for name in RETIRED_READERS if name in read(path)), [])


def load_watcher():
    spec = importlib.util.spec_from_file_location("watch_jobs_under_test", WATCH_JOBS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_watcher_picks_up_a_key_saved_after_it_started(checks):
    print("the job watcher")
    # The monitor's own command, started the way Claude Code starts it, with no key yet.
    with Sandbox(key=None) as box:
        proc = subprocess.Popen(["bash", os.path.join(SCRIPTS, "watch-jobs.sh")], env=box.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.time() + 3
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.1)
        still_running = proc.poll() is None
        proc.kill()
        out, _ = proc.communicate()
        checks.eq("watch-jobs.sh started with no key is still running 3 s later", still_running, True)
        checks.eq("and announced nothing", out, b"")

    # The loop itself, driven in-process: the platform is a stub and each sleep is a step of the
    # story, so this needs no network and no fifteen-second waits. The key is read for real, by
    # the watcher asking mp-auth.sh, from a real file under a fake HOME.
    watcher = load_watcher()
    home = tempfile.mkdtemp(prefix="novadde-watch-")
    data = os.path.join(home, "data")
    os.makedirs(data)
    events, keys_fetched = [], []

    class Stop(Exception):
        pass

    def sleep(seconds):
        sleeps = sum(1 for event in events if event[0] == "sleep")
        events.append(("sleep", seconds))
        if sleeps == 0:
            write_key_file(home, "MODEL_PLATFORM_API_KEY=mp_x\n")  # saved in the user's terminal
            events.append(("saved", "mp_x"))
        elif sleeps == 1:
            write_key_file(home, "MODEL_PLATFORM_API_KEY=mp_y\n")  # and later replaced
            events.append(("saved", "mp_y"))
        else:
            raise Stop

    def fetch(url, key):
        events.append(("fetch", key))
        keys_fetched.append((url, key))
        new = "running" if len(keys_fetched) == 1 else "completed"
        return [{"id": "job-old", "model": "boltzgen", "status": "completed"},
                {"id": "job-new", "model": "boltzgen", "status": new}]

    watcher.time = types.SimpleNamespace(sleep=sleep)
    watcher.fetch = fetch
    saved_env = dict(os.environ)
    for name in ("MP_KEY", "CLAUDE_PLUGIN_DATA") + RETIRED_READERS:
        os.environ.pop(name, None)
    os.environ.update(HOME=home, MP_URL=PLATFORM, NOVADDE_DATA=data, NOVADDE_WATCH_INTERVAL="15")
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

    checks.eq("started with no key, it waited instead of exiting", outcome, "still watching")
    checks.eq("it asked the platform nothing before a key was saved",
              events[:1], [("sleep", 15.0)])
    checks.eq("it picked the saved key up on the next pass, and a replaced one on the pass after",
              keys_fetched, [(PLATFORM, "mp_x"), (PLATFORM, "mp_y")])
    lines = said.getvalue().splitlines()
    checks.eq("the jobs already finished when the key arrived were recorded silently",
              [line for line in lines if "job-old" in line], [])
    checks.eq("and a job finishing after that is announced, once",
              [line.split(" (")[0] for line in lines], ["[novadde-job] Job job-new"])


def test_setup_skill_names_the_keys_page_and_never_asks_for_the_key(checks):
    print("skills/setup/SKILL.md and the README")
    skill = read(SETUP_SKILL)
    end = skill.find("\n---", 3)
    front, body = skill[:end], skill[end:]
    checks.eq("(precondition) the skill has frontmatter", skill.startswith("---") and end > 0, True)
    checks.eq("the agent may invoke it (no disable-model-invocation)",
              "disable-model-invocation" in front, False)
    checks.eq("the only tool it pre-approves is the read-only check",
              [line for line in front.splitlines() if line.startswith("allowed-tools:")],
              ["allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/setup-credential.sh --check)"])
    for needle in ("Continue with Google", PLATFORM + "/keys", "`novadde-plugin`", SHOWN,
                   "Never ask for the key in this conversation"):
        checks.eq(f"the skill says {needle!r}", needle in body, True)
    for needle in ("--key", "--login", "--config api_key", "/plugin configure", "Settings, API keys"):
        checks.eq(f"the skill does not say {needle!r}", needle in skill, False)

    readme = read(README)
    for needle in (PLATFORM + "/keys", SHOWN):
        checks.eq(f"the README says {needle!r}", needle in readme, True)
    for needle in ("--config api_key", "The key is stored twice"):
        checks.eq(f"the README does not say {needle!r}", needle in readme, False)
    skill_saves, readme_saves = saving_one_liners(skill), saving_one_liners(readme)
    checks.eq("(precondition) the skill and the README each give one saving one-liner",
              (len(skill_saves), len(readme_saves)), (1, 1))
    checks.eq("and it is the same one-liner in both", skill_saves == readme_saves, True)


def test_the_one_liner_saves_the_key_where_every_reader_finds_it(checks):
    print("the saving one-liner, run as the user runs it")
    saves = saving_one_liners(read(README))
    helper = headers_helper()
    checks.eq("(precondition) the README has the one-liner, and .mcp.json a helper",
              (len(saves), helper is not None), (1, True))
    if len(saves) != 1 or helper is None:
        return
    one_liner = saves[0]
    new_key = "mp_new_0123456789abcdef"
    home = tempfile.mkdtemp(prefix="novadde-save-")
    env = {"HOME": home, "PATH": "/usr/bin:/bin"}
    try:
        # A lab Mac's file: a URL line other tools use, a comment, and an old exported key.
        before = ("MODEL_PLATFORM_URL=%s\n# the lab's settings\n"
                  "export MODEL_PLATFORM_API_KEY=mp_old\n" % LAB_URL)
        write_key_file(home, before)
        os.chmod(key_file(home), 0o644)
        done = subprocess.run(["bash", "-c", one_liner], input=new_key + "\n", env=env,
                              capture_output=True, text=True, timeout=20)
        checks.eq("it exits 0", done.returncode, 0)
        checks.eq("the file is mode 600", stat.S_IMODE(os.stat(key_file(home)).st_mode), 0o600)
        checks.eq("it replaced only the key line",
                  read(key_file(home)).splitlines(),
                  ["MODEL_PLATFORM_URL=%s" % LAB_URL, "# the lab's settings",
                   "MODEL_PLATFORM_API_KEY=%s" % new_key])
        checks.eq("and never echoed the key", new_key in done.stdout + done.stderr, False)
        checks.eq("the MCP helper now sends the new key",
                  run_helper(helper, home).stdout.decode(),
                  '{"Authorization":"Bearer %s"}' % new_key)
        checks.eq("and the hooks read the same one", hooks_view(home)[1], new_key)
        checks.eq("no temporary file is left beside it",
                  sorted(os.listdir(os.path.dirname(key_file(home)))), ["model-platform.env"])

        saved = read(key_file(home))
        done = subprocess.run(["bash", "-c", one_liner], input="sk-not-a-platform-key\n", env=env,
                              capture_output=True, text=True, timeout=20)
        checks.eq("something that is not an mp_ key is refused (exit 1)", done.returncode, 1)
        checks.eq("and the file is left as it was", read(key_file(home)), saved)

        fresh = tempfile.mkdtemp(prefix="novadde-fresh-")
        try:
            done = subprocess.run(["bash", "-c", one_liner], input=new_key + "\n",
                                  env=dict(env, HOME=fresh), capture_output=True, text=True, timeout=20)
            checks.eq("on a fresh HOME it creates the file, mode 600, holding only the key",
                      (done.returncode, stat.S_IMODE(os.stat(key_file(fresh)).st_mode),
                       read(key_file(fresh))),
                      (0, 0o600, "MODEL_PLATFORM_API_KEY=%s\n" % new_key))
        finally:
            shutil.rmtree(fresh, ignore_errors=True)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main():
    checks = Checks("test_key_file_credential")
    test_headers_helper_prints_the_key_from_the_file(checks)
    test_the_hooks_and_the_helper_read_the_same_key(checks)
    test_mcp_json_carries_no_user_config_and_no_static_authorization(checks)
    test_plugin_json_has_no_api_key_or_platform_url_option(checks)
    test_the_lab_url_line_does_not_move_the_platform(checks)
    test_the_brief_reads_the_file_not_the_option(checks)
    test_the_watcher_picks_up_a_key_saved_after_it_started(checks)
    test_setup_skill_names_the_keys_page_and_never_asks_for_the_key(checks)
    test_the_one_liner_saves_the_key_where_every_reader_finds_it(checks)
    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
