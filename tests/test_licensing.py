"""The plugin says whose each part is: its own LICENSE, and a notice for every skill it did not write.

The repository is published, and the plugin is installed from it on machines outside the lab. Two
things have to hold in every copy:

* The plugin's LICENSE travels with it. An install copies plugins/novadde/ and nothing above it, so
  the license lives there, and the repository root carries the same file for anyone reading the
  repository. The two are held byte for byte, so neither can be edited alone.
* Third-party skills keep their notices. Thirteen of the vendored skills are someone else's work
  under MIT or Apache-2.0, both of which require the license and copyright notice in every copy;
  the vendored copies carried none for nine of them. THIRD-PARTY-NOTICES.md reproduces the terms,
  and it must name every such skill -- including one a re-vendor brings in later, which is why the
  skills are found by what upstream marks them with rather than listed here: a `skill-author`
  (K-Dense's convention), a `vendored-from` (the lab's own, for skills it took from elsewhere), or
  an `UPSTREAM-LICENSE` beside the SKILL.md.

Written for the oldest python3 a Mac ships (3.9) as well as CI's.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import REPO, Checks  # noqa: E402

PLUGIN = os.path.join(REPO, "plugins", "novadde")
SKILLS = os.path.join(PLUGIN, "skills")
NOTICES = os.path.join(PLUGIN, "THIRD-PARTY-NOTICES.md")
MARKS = re.compile(r"^\s*(skill-author|vendored-from)\s*:", re.M)
NAMED = re.compile(r"`skills/([A-Za-z0-9._-]+)`")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def frontmatter(text):
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def third_party():
    """The shipped skills upstream marks as someone else's, each with the marks it carries."""
    found = {}
    for name in sorted(os.listdir(SKILLS)):
        folder = os.path.join(SKILLS, name)
        skill = os.path.join(folder, "SKILL.md")
        if not os.path.isfile(skill):
            continue
        marks = sorted(set(MARKS.findall(frontmatter(read(skill)))))
        if os.path.isfile(os.path.join(folder, "UPSTREAM-LICENSE")):
            marks.append("UPSTREAM-LICENSE")
        if marks:
            found[name] = marks
    return found


def main():
    checks = Checks("test_licensing")

    checks.eq("the repository root and the plugin carry the same LICENSE",
              read(os.path.join(REPO, "LICENSE")), read(os.path.join(PLUGIN, "LICENSE")))
    checks.eq("the LICENSE points at the notices file it defers to",
              "THIRD-PARTY-NOTICES.md" in read(os.path.join(PLUGIN, "LICENSE")), True)

    marked = third_party()
    notices = read(NOTICES)
    named = set(NAMED.findall(notices))
    # A scan that finds nothing would pass the check below; these are the thirteen it must find.
    checks.eq("(precondition) the scan finds the K-Dense and Claude Science skills",
              {"biopython", "rdkit", "glycoengineering", "borzoi", "scgpt"} <= set(marked), True)
    checks.eq("every third-party skill is named in THIRD-PARTY-NOTICES.md",
              sorted(name for name in marked if name not in named), [])
    checks.eq("every skill the notices name is one the plugin ships",
              sorted(name for name in named if not os.path.isdir(os.path.join(SKILLS, name))), [])
    checks.eq("the notices reproduce both licenses in full, not just their names",
              ("Copyright (c) 2025 K-Dense Inc." in notices,
               "The above copyright notice and this permission notice shall be included" in notices,
               "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in notices),
              (True, True, True))
    return checks.done()


if __name__ == "__main__":
    sys.exit(main())
