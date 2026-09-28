"""Every /novadde:<name> or $novadde:<name> the repo tells someone to type is a skill it ships.

A plugin skill is invoked as /<plugin>:<name>, where <name> is the skill's frontmatter `name`
(https://code.claude.com/docs/en/skills). The plugin's own three skills were named with a
`novadde-` prefix, so the command every document gave -- the README, the userConfig description,
status.sh, the SessionStart brief, the job watcher and the skills themselves -- did not exist; the
real one carried the prefix twice. The last two are injected into the agent's context, so the agent
itself told users to type it.

Codex reaches the same skills under the same plugin namespace with a `$` in place of the `/`, so
`$novadde:status` is the Codex spelling of `/novadde:status`. Nothing in the repo spells it that way
yet -- the Codex manifest and the per-host README come later -- so the scan reads both spellings
now, and the first `$novadde:` line to land is held to the same rule. It also proves on a sample
line that it can read one, because a scan blind to the Codex spelling would pass here exactly as it
does today.

Also pins the two spellings that have to move with a rename: the directory (the sync script's OURS
set is a list of directory names, and a name missing from it is deleted on the next re-vendor), and
the frontmatter name (which is what the command is made from).
"""
import ast
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import REPO, Checks  # noqa: E402

PLUGIN = os.path.join(REPO, "plugins", "novadde")
SKILLS = os.path.join(PLUGIN, "skills")
# A command as either host spells it -- Claude Code's `/novadde:` or Codex's `$novadde:` -- preceded
# by nothing that would make it part of a longer path, word or shell word, then a skill name. The
# trailing lookahead stops a name from being cut short at a character we do not allow.
COMMAND = re.compile(r"(?<![\w./$-])[/$]novadde:([A-Za-z0-9_-]+)(?![\w-])")
TEXT_SUFFIXES = {".md", ".py", ".sh", ".json", ".txt", ".yml", ".yaml"}
# Directories the walk skips when there is no git to ask: git's own, and the two .gitignore names.
SKIP_DIRS = (".git", "__pycache__", ".sync-tmp")
# One line with each host's spelling and two near-misses that are not commands: a path that
# happens to contain `/novadde:` and a `$` glued to a preceding word. The walk below reads this file
# like any other and must find exactly the two commands on this line, in order -- which is also why
# they name skills that exist.
SAMPLE = "/novadde:setup in Claude Code, $novadde:status in Codex; not x/novadde:y or a$novadde:z"


def frontmatter_name(path):
    """The `name:` of a SKILL.md's frontmatter block, or None."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "name":
            return value.strip().strip("'\"") or None
    return None


def skills():
    """{directory: frontmatter name} for every skill the plugin ships."""
    found = {}
    for entry in sorted(os.listdir(SKILLS)):
        doc = os.path.join(SKILLS, entry, "SKILL.md")
        if os.path.isfile(doc):
            found[entry] = frontmatter_name(doc)
    return found


def repo_files():
    """Repo-relative paths of the files that are the repo's own: git's view, or the whole tree.

    In a checkout that is `git ls-files` of the tracked files plus the untracked ones no ignore rule
    covers, so a file written but not yet added is still scanned. What git ignores is not: a
    virtualenv (`uv venv` and Python 3.13's `venv` put a `*` .gitignore inside the one they make),
    or a node_modules or editor scratch named in a developer's global excludes. That text is not the
    repo's, and a `/novadde:` or shell `$novadde:` inside it would fail this guard on one laptop
    while CI, whose checkout has nothing untracked, stays green -- and walking it only makes the
    test slow. A tree git does not own -- a `git archive` export, or a copy sitting inside some other
    checkout, whose top level is not this directory -- is walked whole.
    """
    def git(*args):
        try:
            done = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
        except OSError:
            return None
        return done.stdout if done.returncode == 0 else None

    top = git("rev-parse", "--show-toplevel")
    if top and os.path.realpath(top.strip()) == os.path.realpath(REPO):
        listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        if listed is not None:
            return sorted(set(p for p in listed.split("\0") if p))
    paths = []
    for folder, dirs, files in os.walk(REPO):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        paths.extend(os.path.relpath(os.path.join(folder, f), REPO) for f in sorted(files))
    return paths


def references():
    """[(repo-relative path, line number, sigil, name)] for every command in a text file."""
    found = []
    for relative in repo_files():
        if os.path.splitext(relative)[1].lower() not in TEXT_SUFFIXES:
            continue
        try:
            # A path still in git's index but deleted from disk (a rename not yet staged) is
            # skipped here, like a file that is not UTF-8.
            with open(os.path.join(REPO, relative), encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            for match in COMMAND.finditer(line):
                found.append((relative, number, match.group(0)[0], match.group(1)))
    return found


def ours_in_sync_script():
    """The OURS set literal in sync_skills.py, read without importing it."""
    with open(os.path.join(PLUGIN, "scripts", "lib", "sync_skills.py"), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "OURS" for target in node.targets
        ):
            return set(ast.literal_eval(node.value))
    return None


def main():
    checks = Checks("test_skill_commands")
    shipped = skills()
    names = {name for name in shipped.values() if name}
    refs = references()

    # Preconditions: a parser that sees nothing would pass everything below.
    checks.eq("every shipped skill has a frontmatter name",
              sorted(d for d, n in shipped.items() if not n), [])
    checks.eq("the README names at least one /novadde: command",
              any(path == "README.md" and sigil == "/" for path, _, sigil, _ in refs), True)
    here = os.path.relpath(os.path.abspath(__file__), REPO)
    with open(__file__, encoding="utf-8") as handle:
        sample_at = [n for n, line in enumerate(handle.read().splitlines(), 1)
                     if line.startswith("SAMPLE = ")]
    checks.eq("the scan reads Claude Code's /novadde: and Codex's $novadde: on the sample line, "
              "and neither near-miss",
              [(sigil, name) for path, number, sigil, name in refs
               if path == here and [number] == sample_at],
              [("/", "setup"), ("$", "status")])

    unknown = ["%s:%d %snovadde:%s" % ref for ref in refs if ref[3] not in names]
    checks.eq("every /novadde:<name> and $novadde:<name> in the repo is a skill the plugin ships",
              unknown, [])

    with open(os.path.join(SKILLS, ".synced-from"), encoding="utf-8") as handle:
        vendored = set(json.load(handle)["skills"])
    own = {d for d in shipped if d not in vendored}
    checks.eq("the plugin's own skills are the ones the README tells users to type",
              sorted({shipped[d] for d in own}),
              sorted({name for path, _, _, name in refs if path == "README.md"}))
    checks.eq("each own skill's directory is its command name",
              sorted(d for d in own if shipped[d] != d), [])
    checks.eq("sync_skills.py's OURS is exactly the own skills, so a re-vendor keeps them",
              sorted(ours_in_sync_script() or []), sorted(own))
    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
