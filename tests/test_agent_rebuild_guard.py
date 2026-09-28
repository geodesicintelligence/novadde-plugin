"""check.sh fails when agents/novadde.md is not what build-agent.sh builds from prompt/.

The block headed "the agent file is the built one" used to be seven anchor greps. They all passed
with the file duplicated end to end, with the MCP brief moved above the operator prompt, and with
operating principle 17 (the safety red lines) deleted -- and nothing noticed a prompt/ edit that was
never rebuilt. The check now rebuilds offline, from prompt/ and the verbs recorded at the last
build, and compares byte for byte.

Each case runs the real check.sh on a copy of the plugin laid out the way an install is (no
marketplace manifest two levels up), so check.sh skips its own test block and cannot recurse into
this file, with no `claude` on PATH, and in the C locale. The online build is driven through the
fake curl.

Written for the oldest python3 a Mac ships (3.9) as well as CI's.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import REPO, Checks, Sandbox, mcp_tools  # noqa: E402

PLUGIN = os.path.join(REPO, "plugins", "novadde")
AGENT = os.path.join("agents", "novadde.md")
VERBS = os.path.join("prompt", ".built-verbs")
REBUILD_FAIL = "FAIL agents/novadde.md is not what build-agent.sh builds from prompt/"
MISSING_VERBS = "prompt/.built-verbs is missing or empty"
UNREADABLE_VERBS = "prompt/.built-verbs is there but could not be read"
OPERATOR = "Your name is NovaDDE"
MCP_HEADING = "## Structural biology on this deployment"


def installed_copy(box):
    """plugins/novadde copied under a fresh directory with no .claude-plugin/ beside it."""
    dest = os.path.join(tempfile.mkdtemp(dir=box.root), "plugins", "novadde")
    shutil.copytree(PLUGIN, dest, ignore=shutil.ignore_patterns("__pycache__", ".sync-tmp"))
    return dest


def read(plugin, rel):
    with open(os.path.join(plugin, rel), encoding="utf-8") as handle:
        return handle.read()


def write(plugin, rel, text):
    with open(os.path.join(plugin, rel), "w", encoding="utf-8") as handle:
        handle.write(text)


def digest(plugin, rel):
    path = os.path.join(plugin, rel)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def env_without_claude(box):
    env = dict(box.env)
    # The fake curl and the python3 shim, then only the system dirs: a developer's `claude` must
    # not run `plugin validate` on a temp copy.
    env["PATH"] = box.bin + os.pathsep + "/usr/bin:/bin"
    # The C locale, whatever the developer's is. The unreadable-.built-verbs case reads the
    # reader's own error, and GNU cat under a localised LANG with its catalog installed (zh_CN on
    # a Linux box, say) translates "Is a directory" -- a red test with nothing wrong in the code.
    # macOS's BSD cat never translates it, and in the C locale GNU cat does not either.
    env["LC_ALL"] = "C"
    return env


def run_check(box, plugin):
    """check.sh on the copy. Returns (exit code, FAIL lines, stderr, stdout)."""
    done = subprocess.run(
        ["bash", os.path.join(plugin, "scripts", "check.sh")],
        env=env_without_claude(box), capture_output=True, text=True, timeout=120,
    )
    fails = [line for line in (done.stdout + done.stderr).splitlines() if line.startswith("FAIL ")]
    return done.returncode, fails, done.stderr, done.stdout


def run_build(box, plugin):
    return subprocess.run(
        ["bash", os.path.join(plugin, "scripts", "build-agent.sh")],
        env=env_without_claude(box), capture_output=True, text=True, timeout=60,
    )


def ran_the_block(checks, label, stdout):
    # Preconditions: the block ran, and the copy really is install-shaped (no recursion into the
    # tests, no claude validate), so a pass or a fail below is about the agent file.
    checks.eq(f"{label}: check.sh reached the agent-file block",
              "== the agent file is the built one ==" in stdout, True)
    checks.eq(f"{label}: and did not run the test suite from the copy",
              "== script behaviour ==" in stdout, False)
    checks.eq(f"{label}: and did not run claude plugin validate",
              "== claude plugin validate: skipped, no claude on PATH ==" in stdout, True)


def drop_principle_17(text):
    start = text.index("\n17. **Safety red lines")
    end = text.index("\n18. **", start)
    return text[:start] + text[end:]


def mcp_brief_first(text):
    start = text.index(MCP_HEADING)
    end = text.index("<RESPONSE_QUALITY>", start)
    block, rest = text[start:end], text[:start] + text[end:]
    after_frontmatter = rest.index("\n---\n", 3) + len("\n---\n")
    return rest[:after_frontmatter] + "\n" + block + rest[after_frontmatter:]


def main():
    checks = Checks("test_agent_rebuild_guard")

    # The pristine tree passes, offline, and the check writes nothing.
    with Sandbox(key=None) as box:
        plugin = installed_copy(box)
        before = (digest(plugin, AGENT), digest(plugin, VERBS))
        code, fails, _, out = run_check(box, plugin)
        ran_the_block(checks, "pristine", out)
        checks.eq("pristine: no check fails", fails, [])
        checks.eq("pristine: check.sh exits 0", code, 0)
        checks.eq("pristine: the check rewrites neither the agent file nor the verbs",
                  (digest(plugin, AGENT), digest(plugin, VERBS)), before)
        checks.eq("pristine: the check never probes the platform", box.calls(), [])

    # Each edit the anchor greps let through. (label, file to change, change, and a line the diff
    # must show -- (prefix, text in it), committed -> rebuilt -- so the reader sees what moved)
    mutations = [
        ("principle 17 deleted from the agent file", AGENT, drop_principle_17,
         ("+17. **Safety red lines", "")),
        ("the agent file duplicated end to end", AGENT, lambda text: text + text, None),
        ("the MCP brief moved above the operator prompt", AGENT, mcp_brief_first, None),
        ("prompt/workspace-brief.md edited without rebuilding", "prompt/workspace-brief.md",
         lambda text: text + "An edit nobody rebuilt.\n", ("+An edit nobody rebuilt.", "")),
        ("principle 17 deleted from prompt/ without rebuilding", "prompt/system-prompt.md",
         drop_principle_17, ("-17. **Safety red lines", "")),
        ("a verb recorded in .built-verbs without rebuilding", VERBS,
         lambda text: text + "brand_new_verb\n", ("+`model_platform` (", "`brand_new_verb`")),
    ]
    for label, rel, change, diff_line in mutations:
        with Sandbox(key=None) as box:
            plugin = installed_copy(box)
            original = read(plugin, rel)
            write(plugin, rel, change(original))
            checks.eq(f"{label}: (precondition) the edit took", read(plugin, rel) != original, True)
            code, fails, err, out = run_check(box, plugin)
            ran_the_block(checks, label, out)
            checks.eq(f"{label}: fails the rebuild check and nothing else", fails, [REBUILD_FAIL])
            checks.eq(f"{label}: check.sh exits 1", code, 1)
            if diff_line:
                prefix, needle = diff_line
                checks.eq(f"{label}: the failure's diff shows {prefix!r}",
                          any(line.startswith(prefix) and needle in line
                              for line in err.splitlines()), True)

    # Sanity of the mutation helpers themselves, so a case above cannot pass on a no-op edit.
    pristine = read(PLUGIN, AGENT)
    checks.eq("(precondition) the pristine file has principle 17",
              "17. **Safety red lines" in pristine, True)
    checks.eq("(precondition) dropping it removes it",
              "17. **Safety red lines" in drop_principle_17(pristine), False)
    moved = mcp_brief_first(pristine)
    checks.eq("(precondition) moving the MCP brief puts it above the operator prompt",
              moved.index(MCP_HEADING) < moved.index(OPERATOR), True)

    # A missing .built-verbs is a failure, not a brief with an empty verb list.
    with Sandbox(key=None) as box:
        plugin = installed_copy(box)
        os.remove(os.path.join(plugin, VERBS))
        code, fails, err, out = run_check(box, plugin)
        ran_the_block(checks, "no .built-verbs", out)
        checks.eq("no .built-verbs: fails the rebuild check", fails, [REBUILD_FAIL])
        checks.eq("no .built-verbs: check.sh exits 1", code, 1)
        checks.eq("no .built-verbs: the check says the verbs are missing", MISSING_VERBS in err, True)

    # A .built-verbs that is there but cannot be read is a different fault, and the check must not
    # file it under "missing or empty": that message sends the reader to rebuild online, when the
    # real cause is the read (a permission, or a test that pins PATH and leaves out `cat`). A
    # directory in its place fails the read the same way for every user, root included.
    with Sandbox(key=None) as box:
        plugin = installed_copy(box)
        verbs_path = os.path.join(plugin, VERBS)
        os.remove(verbs_path)
        os.makedirs(verbs_path)
        write(plugin, os.path.join(VERBS, "list_models"), "")
        checks.eq("unreadable .built-verbs: (precondition) it is there and not empty, as [ -s ] sees it",
                  os.path.isdir(verbs_path) and os.path.getsize(verbs_path) > 0, True)
        code, fails, err, out = run_check(box, plugin)
        ran_the_block(checks, "unreadable .built-verbs", out)
        checks.eq("unreadable .built-verbs: fails the rebuild check", fails, [REBUILD_FAIL])
        checks.eq("unreadable .built-verbs: check.sh exits 1", code, 1)
        checks.eq("unreadable .built-verbs: is not reported as missing or empty",
                  MISSING_VERBS in err, False)
        checks.eq("unreadable .built-verbs: says the file is there but could not be read",
                  UNREADABLE_VERBS in err, True)
        checks.eq("unreadable .built-verbs: the reader's own error names the file",
                  any(".built-verbs" in line and "Is a directory" in line
                      for line in err.splitlines()), True)

    # The online build and the offline check share one assembly: probing the verbs the tree was
    # built with reproduces the committed file byte for byte.
    committed_verbs = [v for v in read(PLUGIN, VERBS).splitlines() if v]
    with Sandbox({"POST /api/mcp": mcp_tools(*committed_verbs)}, key=None) as box:
        plugin = installed_copy(box)
        before = (digest(plugin, AGENT), digest(plugin, VERBS))
        built = run_build(box, plugin)
        checks.eq("online build, same verbs: exits 0", built.returncode, 0)
        checks.eq("online build, same verbs: (precondition) it asked the platform",
                  sum(1 for call in box.calls() if call["path"] == "/api/mcp"), 1)
        checks.eq("online build, same verbs: agent file and verbs are byte-identical",
                  (digest(plugin, AGENT), digest(plugin, VERBS)), before)

    # A verb the platform newly serves: the online build takes it, and the check agrees with it.
    with Sandbox({"POST /api/mcp": mcp_tools(*(committed_verbs + ["brand_new_verb"]))},
                 key=None) as box:
        plugin = installed_copy(box)
        built = run_build(box, plugin)
        checks.eq("online build, new verb: exits 0", built.returncode, 0)
        checks.eq("online build, new verb: the brief names it",
                  "`brand_new_verb`" in read(plugin, AGENT), True)
        checks.eq("online build, new verb: .built-verbs records it",
                  read(plugin, VERBS).splitlines()[-1], "brand_new_verb")
        code, fails, _, out = run_check(box, plugin)
        checks.eq("online build, new verb: check.sh accepts what the build wrote", fails, [])

    # The platform does not answer: the build refuses and leaves the tree alone.
    with Sandbox(key=None) as box:
        plugin = installed_copy(box)
        before = (digest(plugin, AGENT), digest(plugin, VERBS))
        built = run_build(box, plugin)
        checks.eq("online build, no platform: exits 1", built.returncode, 1)
        checks.eq("online build, no platform: the tree is untouched",
                  (digest(plugin, AGENT), digest(plugin, VERBS)), before)

    # What the rebuild cannot see is the pieces themselves: an empty operator prompt, rebuilt,
    # reproduces exactly. The size floor and the identity grep kept in check.sh catch that.
    with Sandbox({"POST /api/mcp": mcp_tools(*committed_verbs)}, key=None) as box:
        plugin = installed_copy(box)
        write(plugin, "prompt/system-prompt.md", "")
        checks.eq("empty operator prompt: (precondition) rebuilt online",
                  run_build(box, plugin).returncode, 0)
        code, fails, _, out = run_check(box, plugin)
        checks.eq("empty operator prompt: the rebuild itself matches", REBUILD_FAIL in fails, False)
        checks.eq("empty operator prompt: the size floor fails",
                  any(f.startswith("FAIL agents/novadde.md looks unbuilt") for f in fails), True)
        checks.eq("empty operator prompt: the identity grep fails",
                  "FAIL the operator prompt is missing" in fails, True)
        checks.eq("empty operator prompt: check.sh exits 1", code, 1)

    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
