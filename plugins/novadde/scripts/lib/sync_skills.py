"""Vendor the lab's science skills into this plugin.

The deployment copies `geodesic-science-skills` into every container's `~/.claude/skills`. A
plugin ships them in its own `skills/` directory instead, which changes one thing that matters:
where a skill's bundled scripts live. That repo's README mandates absolute paths of the form
`python3 ~/.claude/skills/<name>/scripts/foo.py`, precisely because the agent's working directory
is not the skill's. Inside a plugin that path does not exist, so every one of them is rewritten:

* a skill pointing at its OWN files becomes `${CLAUDE_SKILL_DIR}/...`
* a skill pointing at ANOTHER skill's files becomes `${CLAUDE_PLUGIN_ROOT}/skills/<other>/...`,
  because CLAUDE_SKILL_DIR is the invoked skill's directory and would resolve to the wrong one.

Also asserts that no `中文触发语` block survives in a description. The control plane strips those
before writing a skill to disk, having measured that every skill description is in every prompt and
that the phrases were pulling English conversations into Chinese. A vendored copy has to match.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO = "https://github.com/geodesicintelligence/geodesic-science-skills"
#: The plugin's own skills, by directory. The directory, the frontmatter `name` and the command are
#: one spelling: a plugin skill is invoked as /novadde:<name> (on Codex, $novadde:<name>), so these
#: are /novadde:setup, /novadde:status and /novadde:examples. A name missing here is deleted by the
#: next re-vendor, and an upstream skill of the same name is refused below rather than copied over.
OURS = {"setup", "status", "examples"}
#: Upstream skills that only make sense where the control plane put them. The science repo's own
#: install smoke test checks that `install.sh` symlinked skills into `~/.claude/skills/`, which is
#: not how a plugin ships them, so vendoring it would hand the agent a check that fails by
#: construction. Upstream has since renamed it `internal-test` and marks it as synced to no
#: deployment either, so both names are here: a re-vendor from either side of the rename skips it.
EXCLUDE = {
    "test": "a smoke test for the science repo's symlink install path",
    "internal-test": "a smoke test for the science repo's symlink install path",
}
TEXT_SUFFIXES = {".md", ".py", ".sh", ".txt", ".json", ".yaml", ".yml"}
HOME_SKILL = re.compile(r"(?:~|\$HOME|\$\{HOME\})/\.claude/skills/([a-zA-Z0-9._-]+)(/?)")
TRIGGER_MARKERS = ("中文触发语", "中文触發語")


def run(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def rewrite(path: str, own_skill: str) -> int:
    try:
        with open(path, encoding="utf-8") as handle:
            before = handle.read()
    except (OSError, UnicodeDecodeError):
        return 0

    def one(match: re.Match) -> str:
        named, slash = match.group(1), match.group(2)
        if named == own_skill:
            return "${CLAUDE_SKILL_DIR}" + slash
        return "${CLAUDE_PLUGIN_ROOT}/skills/" + named + slash

    after, count = HOME_SKILL.subn(one, before)
    if count:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(after)
    return count


def frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def main() -> int:
    root = sys.argv[1]
    dest_root = os.path.join(root, "skills")
    work = os.path.join(root, ".sync-tmp")
    shutil.rmtree(work, ignore_errors=True)
    print(f"cloning {REPO} ...")
    run("git", "clone", "--depth", "1", "--quiet", REPO, work)
    commit = run("git", "-C", work, "rev-parse", "HEAD")
    source = os.path.join(work, "skills")
    if not os.path.isdir(source):
        print("sync-skills: the repo has no skills/ directory", file=sys.stderr)
        return 1

    # Ours are never touched; everything else in skills/ is the vendored set and is replaced
    # wholesale, so a skill deleted upstream disappears here too.
    for existing in sorted(os.listdir(dest_root)) if os.path.isdir(dest_root) else []:
        if existing in OURS or existing.startswith("."):
            continue
        shutil.rmtree(os.path.join(dest_root, existing), ignore_errors=True)
    os.makedirs(dest_root, exist_ok=True)

    vendored, skipped, rewrites, problems = [], [], 0, []
    for name in sorted(os.listdir(source)):
        src = os.path.join(source, name)
        if not os.path.isdir(src) or not os.path.isfile(os.path.join(src, "SKILL.md")):
            continue
        if name in OURS:
            problems.append(f"upstream skill {name!r} collides with one of this plugin's own")
            continue
        if name in EXCLUDE:
            skipped.append(f"{name} ({EXCLUDE[name]})")
            continue
        dst = os.path.join(dest_root, name)
        shutil.copytree(src, dst)
        for folder, _, files in os.walk(dst):
            for filename in files:
                if os.path.splitext(filename)[1].lower() in TEXT_SUFFIXES:
                    rewrites += rewrite(os.path.join(folder, filename), name)
        with open(os.path.join(dst, "SKILL.md"), encoding="utf-8") as handle:
            front = frontmatter(handle.read())
        for marker in TRIGGER_MARKERS:
            if marker in front:
                problems.append(f"{name}: {marker} block still in the description")
        vendored.append(name)

    shutil.rmtree(work, ignore_errors=True)

    with open(os.path.join(dest_root, ".synced-from"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "repo": REPO,
                "commit": commit,
                "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "skills": vendored,
                "excluded": skipped,
            },
            handle,
            indent=2,
        )
        handle.write("\n")

    print(f"vendored {len(vendored)} skills from {commit[:9]}, {rewrites} script paths rewritten")
    for entry in skipped:
        print(f"skipped  {entry}")
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
