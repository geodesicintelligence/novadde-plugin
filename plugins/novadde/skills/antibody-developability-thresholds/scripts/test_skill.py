#!/usr/bin/env python3
"""Checks on the SKILL.md that the script's own --selftest cannot make.

This skill is almost entirely numbers copied out of three papers and a web page. The failure
mode is not a bug, it is a transcription: a threshold in the prose drifting from the one the
script applies, or from the source it cites. So every number quoted in the prose is checked
against the script, and the script's own threshold tables are checked for the internal
invariant that TAP's definition of "red" implies.

Run: python3 ${CLAUDE_SKILL_DIR}/scripts/test_skill.py
"""

from __future__ import annotations

import getpass
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
SCRIPT = HERE / "tap_descriptors.py"
sys.path.insert(0, str(HERE))

_ok = True


def check(label, got, want):
    global _ok
    good = got == want
    _ok = _ok and good
    print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")


def main() -> int:
    import tap_descriptors as td

    text = SKILL_MD.read_text()
    fm = text.split("---")[1]

    print("frontmatter survives the loader that can drop the skill")
    keys = [ln.split(":", 1)[0] for ln in fm.splitlines() if ln and not ln[:1].isspace()]
    check("exactly the two house keys", keys, ["name", "description"])
    name = re.search(r"^name:\s*(.+)$", fm, re.M).group(1).strip()
    desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1).strip()
    check("name equals the directory", name, SKILL_DIR.name)
    check("name matches the SDK pattern",
          bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)), True)
    check("description is one line under the 1024 truncation",
          len(desc) <= 1024 and "\n" not in desc, True)
    check("description names both sibling skills",
          "antibody-liabilities" in desc and "antibody-interface-metrics" in desc, True)

    print("invocations resolve")
    body = "\n".join(re.findall(r"```bash\n(.*?)```", text, re.DOTALL))
    check("no relative script path", re.findall(r"python3?\s+scripts/", body), [])
    for skill_name, script_name in set(
        re.findall(r"~/\.claude/skills/([a-z0-9-]+)/scripts/(\S+?\.py)", body)
    ):
        check(f"invocation targets this skill ({script_name})", skill_name, name)
        check(f"referenced script exists ({script_name})", (HERE / script_name).is_file(), True)
    documented = set(re.findall(r"(--[a-z][a-z-]+)", text))
    helptext = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                              capture_output=True, text=True, check=True).stdout
    check("no flag documented that does not exist",
          sorted(documented - set(re.findall(r"(--[a-z][a-z-]+)", helptext))), [])

    print("every threshold in the prose is the one the script applies")
    for key, expected in (
        ("2019", "amber 54–60, red > 60"),
        ("tap2-2024", "amber 37–42 and 55–63, red < 37 or > 63"),
        ("live-2025", "amber 37–42 and 55–65, red < 37 or > 65"),
    ):
        check(f"{key} row present in the table",
              " ".join(expected.split()) in " ".join(text.split()), True)
    s = td.THRESHOLDS
    check("2019 high band matches the prose", s["2019"]["amber_high"], (54, 60))
    check("tap2-2024 bands match", (s["tap2-2024"]["amber_low"], s["tap2-2024"]["amber_high"]),
          ((37, 42), (55, 63)))
    check("live-2025 bands match", (s["live-2025"]["amber_low"], s["live-2025"]["amber_high"]),
          ((37, 42), (55, 65)))

    print("the worked disagreement in the prose is reproducible")
    six = dict(zip(td.CDR_NAMES, [13, 13, 16, 8, 4, 10]))  # 64
    check("that example really totals 64",
          td.total_cdr_length(six, "tap2-2024")["total_cdr_length"], 64)
    for setname, flag in (("tap2-2024", "red"), ("live-2025", "amber"), ("2019", "red")):
        check(f"64 is {flag} under {setname}", td.total_cdr_length(six, setname)["flag"], flag)
    check("...and the prose says so",
          "red under `tap2-2024`, **amber** under `live-2025`, and red under `2019`" in text, True)

    print("red means outside the range, so outer amber == red")
    for setname in ("tap2-2024", "live-2025"):
        spec = s[setname]
        check(f"{setname} high", spec["amber_high"][1], spec["red_high"])
        check(f"{setname} low", spec["amber_low"][0], spec["red_low"])

    print("the four refusals stay refused")
    r = td.refused()
    check("all four, SFvCSP included", sorted(r), ["PNC", "PPC", "PSH", "SFvCSP"])
    check("none carries a number", any("value" in v or "score" in v for v in r.values()), False)
    check("the prose warns SFvCSP is not FvCSP",
          "FvCSP **0** against SFvCSP **+2.0**" in text, True)
    check("and the table marks it refused", "| **SFvCSP** structural Fv charge symmetry | a 3D Fv model | refused |" in text, True)

    print("the claims that limit the skill are present")
    # Matched against a whitespace-normalised copy: this prose is hard-wrapped, so an exact
    # substring check fails on a newline that falls mid-sentence and reports a missing claim
    # that is right there. Found the first time this test ran.
    flat = " ".join(text.split())
    for claim, why in (
        ("no single domain antibodies were carried forward", "the VHH exclusion, quoted"),
        ("48.02 ± 3.77", "the mean that implies all six CDRs"),
        ("27–38, 56–65, 105–117", "the IMGT spans TAP uses"),
        ("Chothia", "the comparability trap with our own numbering skill"),
        ("should not be interpreted as hard-and-fast rules", "the authors' own caveat"),
        ("4.43 vs 5.67", "the live page's internal inconsistency"),
        ("isoelectric", "the Jain-has-no-pI correction"),
        ("What is not established", "the section admitting what is unsourced"),
    ):
        check(f"{why}", " ".join(claim.split()) in flat, True)

    print("repo hygiene")
    needles = ["/" + "Users" + "/", "/" + "home" + "/"]
    try:
        needles.append(getpass.getuser())
    except Exception:
        print("  note: no username available here, checking paths only")
    for path in (SKILL_MD, SCRIPT, Path(__file__)):
        check(f"no home paths in {path.name}",
              sorted(n for n in needles if n in path.read_text()), [])

    print("\n" + ("skill test passed" if _ok else "SKILL TEST FAILED"))
    return 0 if _ok else 1


if __name__ == "__main__":
    sys.exit(main())
