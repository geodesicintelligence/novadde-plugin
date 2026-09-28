"""Every script path a vendored skill names has to resolve inside this plugin.

This is the invariant the path rewrite exists to keep, checked once here rather than five times in
the upstream skills' own self-tests -- those look for the `~/.claude/skills/...` spelling the
rewrite removes, so after vendoring they check nothing at all. A broken path is not a cosmetic
problem: `<available_skills>` renders no location field, so an agent that cannot resolve the path
in the skill body has no second way to find the script.
"""
import os
import re
import sys

INVOCATION = re.compile(
    r"\$\{CLAUDE_SKILL_DIR\}/(\S+?\.(?:py|sh))"
    r"|\$\{CLAUDE_PLUGIN_ROOT\}/skills/([a-z0-9._-]+)/(\S+?\.(?:py|sh))"
)
STALE = re.compile(r"(?:~|\$HOME|\$\{HOME\})/\.claude/skills/[a-zA-Z0-9._-]+/\S*\.(?:py|sh)")


def main() -> int:
    root = sys.argv[1]
    skills_dir = os.path.join(root, "skills")
    failures = []
    checked = 0
    for name in sorted(os.listdir(skills_dir)):
        skill = os.path.join(skills_dir, name)
        doc = os.path.join(skill, "SKILL.md")
        if not os.path.isfile(doc):
            continue
        with open(doc, encoding="utf-8") as handle:
            text = handle.read()
        for stale in STALE.findall(text):
            failures.append(f"{name}: still names the container path {stale}")
        for own, other_skill, other_path in INVOCATION.findall(text):
            # `scripts/<name>.py` is a documentation placeholder, not a path to resolve.
            if "<" in (own or other_path):
                continue
            checked += 1
            if own:
                target = os.path.join(skill, own)
                label = f"{name}: ${{CLAUDE_SKILL_DIR}}/{own}"
            else:
                target = os.path.join(skills_dir, other_skill, other_path)
                label = f"{name}: ${{CLAUDE_PLUGIN_ROOT}}/skills/{other_skill}/{other_path}"
            if not os.path.isfile(target):
                failures.append(f"{label} does not exist")
    print(f"checked {checked} script invocations across the vendored skills")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
