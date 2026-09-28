#!/usr/bin/env python3
"""Guard for binder-fold-stability.

The point of this file is to fail when SKILL.md and the scripts drift apart. A doc that
quotes a cutoff the code does not use is worse than no doc, because it reads as measured.
So the numeric claims are checked against the code that produces them, not against a copy.

Offline. Run: python3 test_skill.py
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
RMSD = HERE / "apo_holo_rmsd.py"
CONTACTS = HERE / "hotspot_contacts.py"

sys.path.insert(0, str(HERE))
import hotspot_contacts as hc          # noqa: E402
import apo_holo_rmsd as ahr            # noqa: E402

_ok = True


def check(label, got, want):
    global _ok
    good = got == want
    _ok = _ok and good
    print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")


def main() -> int:
    text = SKILL_MD.read_text()
    flat = " ".join(text.split())
    # Claim checks run against emphasis-stripped prose: "**more** permissive" and "more
    # permissive" are the same claim, and a test that fails on a bold marker teaches the
    # author to edit the doc to suit the test, which is backwards.
    plain = flat.replace("**", "").replace("`", "")

    print("frontmatter is what the loader will accept")
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    check("frontmatter parses", fm is not None, True)
    name = re.search(r"^name: (.+)$", fm.group(1), re.M).group(1).strip()
    desc = re.search(r"^description: (.+)$", fm.group(1), re.M).group(1).strip()
    check("name is a valid slug", bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)), True)
    check("name equals the directory", name, SKILL_DIR.name)
    check("description fits the 1024 cap", len(desc) <= 1024, True)

    print("invocations use the absolute skills path, not a relative one")
    invocations = re.findall(r"python3 (\S+\.py)", text)
    check("at least one is shown", len(invocations) >= 2, True)
    for inv in set(invocations):
        check(f"{inv.split('/')[-1]} is addressed absolutely",
              inv.startswith("${CLAUDE_SKILL_DIR}/scripts/"), True)
        check(f"{inv.split('/')[-1]} exists", (HERE / inv.split("/")[-1]).is_file(), True)

    print("the distance table in the doc matches the code's own definitions")
    for label, cutoff in (("heavy-5", 5.0), ("cb-8", 8.0), ("cb-13", 13.0)):
        check(f"{label} cutoff agrees", hc.DEFINITIONS[label][0], cutoff)
        check(f"{label} is quoted in the doc", label in flat, True)
    check("the doc names no definition the code lacks",
          sorted(set(re.findall(r"`(heavy-\d+|cb-\d+)`", text)) - set(hc.DEFINITIONS)), [])
    check("and the code ships no definition the doc omits",
          sorted(d for d in hc.DEFINITIONS if d not in flat), [])

    print("the doc says the cutoff is inclusive -- so the code must be")
    import tempfile                                    # noqa: PLC0415
    tmp = Path(tempfile.mkdtemp())
    edge = tmp / "edge.pdb"
    edge.write_text(
        "ATOM      1  CB  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      2  CB  ALA B   1       8.000   0.000   0.000  1.00  0.00           C\nEND\n")
    check("exactly at the cutoff counts",
          hc.contacts(edge, ["A"], ["B"], ["1"], "cb-8")["hotspots_contacted"], 1)
    check("the doc states that choice", "inclusive" in plain, True)

    print("the doc says --plddt is opt-in -- so it must be")
    apo = tmp / "a.pdb"
    apo.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 90.00           C\n"
        "ATOM      2  CA  ALA A   2       3.800   0.000   0.000  1.00 90.00           C\nEND\n")
    check("absent by default", "apo_confidence" in ahr.compare(apo, apo, ["A"], None), False)
    check("present on request", "apo_confidence" in ahr.compare(apo, apo, ["A"], None, True), True)
    check("a 0-100 file is normalised, not compared raw",
          ahr.confidence(ahr.load_ca(apo, {"A"}), ["A"])["mean_plddt"], 0.9)

    print("the thresholds are presented as uncalibrated, with provenance")
    for claim, why in (
        ("bionemo-agent-toolkit", "the source is named"),
        ("0e67a61", "pinned to a commit"),
        ("Apache-2.0", "and its licence"),
        ("not calibrated", "they are marked uncalibrated"),
        ("calibrate on your own actives and decoys", "and the user is told what to do instead"),
    ):
        check(why, claim in plain, True)

    print("every ipTM value the doc attributes to the toolkit is distinct")
    quoted = re.findall(r"ipTM >= (\d\.\d+)|AF2_IPTM_MIN = (\d\.\d+)|ipTM=0\.62 < (\d\.\d+)", text)
    vals = sorted({v for grp in quoted for v in grp if v})
    check("four sources, three distinct values", vals, ["0.65", "0.70", "0.8"])
    check("the contradiction is the stated point", "contradicts itself" in plain, True)

    print("the failure mode this skill exists for is stated, not implied")
    for claim, why in (
        ("only folds because the target is holding it", "the failure mode"),
        ("invisible to ipTM", "and that interface scores cannot see it"),
        ("filter that removes designs", "and what a pass does not prove"),
    ):
        check(why, claim in plain, True)

    print("deployment claims are the measured ones, not the toolkit's")
    for claim, why in (
        ("OOMs on this deployment", "single-sequence OOM is recorded"),
        ("no model on this deployment emits one", "and the missing PAE matrix"),
        ("more permissive, not less", "with the direction of the resulting bias"),
    ):
        check(why, claim in plain, True)

    print("both scripts' own selftests actually run")
    for script in (RMSD, CONTACTS):
        out = subprocess.run([sys.executable, str(script), "--selftest"],
                             capture_output=True, text=True)
        check(f"{script.name} passes", out.returncode, 0)
        check(f"{script.name} is not vacuous", out.stdout.count("PASS") >= 12, True)

    print("repo hygiene")
    needles = ["/" + "Users" + "/", "/" + "home" + "/"]
    try:
        needles.append(getpass.getuser())
    except Exception:
        print("  note: no username available here, checking paths only")
    for path in (SKILL_MD, RMSD, CONTACTS, Path(__file__)):
        check(f"no home paths in {path.name}",
              sorted(n for n in needles if n in path.read_text()), [])

    print("\n" + ("skill test passed" if _ok else "SKILL TEST FAILED"))
    return 0 if _ok else 1


if __name__ == "__main__":
    sys.exit(main())
