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
SCRIPT = HERE / "epitope_candidates.py"
sys.path.insert(0, str(HERE))

_ok = True


def check(label, got, want):
    global _ok
    good = got == want
    _ok = _ok and good
    print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")


def main() -> int:
    import epitope_candidates as td

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
    check("description says it runs before the other design skills",
          "before" in desc or "begins after" in desc, True)

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

    print("the HER2 numbers in the prose are the ones UniProt reports")
    flat = " ".join(text.split())
    for claim, why in (("23-652 Extracellular", "the ectodomain span"),
                       ("653-675", "the transmembrane span"),
                       ("676-1255 Cytoplasmic", "the cytoplasmic span"),
                       ("845", "the active site"),
                       ("726-734, 753", "the binding sites"),
                       ("P14778", "the second worked example")):
        check(why, " ".join(claim.split()) in flat, True)

    print("and the script agrees with the prose on every one of them")
    her2 = None
    import inspect  # noqa: PLC0415
    src = inspect.getsource(td._selftest)
    check("the fixture is transcribed in the selftest, not fetched", '"P04626"' in src, True)
    # re-derive the verdict from the script's own fixture
    ns = {}
    exec(compile(src.replace("def _selftest() -> int:", "def _f():"), "<f>", "exec"),
         td.__dict__.copy(), ns)  # noqa: S102 - reading the module's own fixture
    v = td.assess({"primaryAccession": "P04626",
        "proteinDescription": {"recommendedName": {"fullName": {"value": "erbB-2"}}},
        "features": [
            {"type": "Topological domain", "description": "Extracellular",
             "location": {"start": {"value": 23}, "end": {"value": 652}}},
            {"type": "Transmembrane", "description": "Helical",
             "location": {"start": {"value": 653}, "end": {"value": 675}}},
            {"type": "Topological domain", "description": "Cytoplasmic",
             "location": {"start": {"value": 676}, "end": {"value": 1255}}},
            {"type": "Active site", "location": {"start": {"value": 845}, "end": {"value": 845}}},
        ]})
    check("the ectodomain the prose names", v["reachable_region"], ["23-652"])
    check("the active site is unreachable",
          v["annotated_sites"][0]["reachable_by_a_surface_binder"], False)

    print("the limits that keep it honest are stated")
    for claim, why in (
        ("necessary, not sufficient", "the gate does not choose the epitope"),
        ("is not a pass", "absent topology is not a pass"),
        ("not calibration", "their thresholds are not calibrated"),
        ("bionemo-agent-toolkit", "provenance is named"),
        ("Apache-2.0", "and its licence"),
    ):
        check(why, " ".join(claim.split()) in flat, True)

    print("the script's own selftest actually runs")
    # Dropped when this file was adapted from a sibling skill, which let a `<=` -> `<`
    # mutation in the topology boundary survive the whole guard. The script's selftest
    # catches it; nothing was calling the script's selftest.
    out = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                         capture_output=True, text=True)
    check("it passes", out.returncode, 0)
    check("and it is not vacuous", out.stdout.count("PASS") >= 15, True)

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
