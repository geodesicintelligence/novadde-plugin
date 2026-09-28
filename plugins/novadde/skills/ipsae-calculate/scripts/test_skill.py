#!/usr/bin/env python3
"""Checks on the SKILL.md itself, which `ipsae.py --selftest` structurally cannot make.

A script selftest proves the arithmetic. It cannot notice that the skill has no SKILL.md, that
the frontmatter fails the loader and the skill is dropped with a log line nobody reads, that a
documented flag was renamed, or that a number quoted in the prose stopped being the number the
script prints. Every check here is one of those, and each corresponds to a defect that has
actually happened in this repo or its deployment:

  no SKILL.md            a skill directory with scripts and no SKILL.md is copied to the
                         container and offered to nobody -- nothing warns.
  bad frontmatter        the agent-side loader parses with real YAML and enforces name
                         <= 64 chars matching ^[a-z0-9]+(-[a-z0-9]+)*$ AND equal to the
                         directory name, truncating description at 1024. A failure drops
                         that one skill with only a logger.warning.
  relative script path   every invocation in this repo was `python3 scripts/foo.py` and
                         none could run: only <name> and <description> reach the prompt,
                         <location> is omitted on purpose, and the agent's cwd is the
                         conversation's project directory.
  documentation drift    a sibling skill's worked example still quotes a d0 convention its
                         own invariants section calls wrong. Prose does not fail a build.

Run: python3 ${CLAUDE_SKILL_DIR}/scripts/test_skill.py
"""

from __future__ import annotations

import getpass
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
SCRIPT = HERE / "ipsae.py"

sys.path.insert(0, str(HERE))

_ok = True


def check(label, got, want):
    global _ok
    good = abs(got - want) < 1e-9 if isinstance(want, float) else got == want
    _ok = _ok and good
    print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")


def frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else ""


def bash_fences(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)


def main() -> int:
    print("the file exists at all")
    check("SKILL.md is present", SKILL_MD.is_file(), True)
    if not SKILL_MD.is_file():
        print("\nSKILL TEST FAILED")
        return 1
    text = SKILL_MD.read_text()
    fm = frontmatter(text)
    check("frontmatter block is delimited", bool(fm), True)

    print("frontmatter survives the loader that can drop the skill")
    keys = [ln.split(":", 1)[0] for ln in fm.splitlines() if ln and not ln[:1].isspace()]
    check("exactly the two house keys, in order", keys, ["name", "description"])
    name = re.search(r"^name:\s*(.+)$", fm, re.M).group(1).strip()
    desc_line = re.search(r"^description:\s*(.+)$", fm, re.M).group(1).strip()
    check("name matches the SDK's pattern",
          bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)), True)
    check("name equals the directory name", name, SKILL_DIR.name)
    check("name within 64 chars", len(name) <= 64, True)
    check("description is a single line, not a block scalar",
          desc_line[:1] not in ("|", ">"), True)
    check("description within the 1024-char truncation", len(desc_line) <= 1024, True)
    check("description names the skill that owns interpretation",
          "antibody-interface-metrics" in desc_line, True)
    check("description carries trigger phrases", desc_line.count('"') >= 6, True)
    try:
        import yaml  # noqa: PLC0415
        parsed = yaml.safe_load(fm)
        check("strict YAML parse yields both fields",
              sorted(parsed) == ["description", "name"], True)
    except ImportError:
        print("  SKIP  strict YAML parse: PyYAML not importable here "
              "(the agent-side loader uses it -- this check is not optional there)")

    print("every invocation the prose gives can actually run")
    fences = bash_fences(text)
    check("SKILL.md has runnable examples", len(fences) >= 1, True)
    body = "\n".join(fences)
    relative = re.findall(r"python3?\s+scripts/\S+", body)
    check("no relative script path (they resolve against the wrong cwd)", relative, [])
    invocations = re.findall(r"~/\.claude/skills/([a-z0-9-]+)/scripts/(\S+?\.py)", body)
    check("at least one absolute invocation", len(invocations) >= 1, True)
    for skill_name, script_name in set(invocations):
        check(f"invocation targets this skill ({script_name})", skill_name, name)
        check(f"referenced script exists ({script_name})",
              (HERE / script_name).is_file(), True)

    print("every flag the prose names still exists")
    helptext = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                              capture_output=True, text=True, check=True).stdout
    real_flags = set(re.findall(r"(--[a-z][a-z-]+)", helptext))
    documented = set(re.findall(r"(--[a-z][a-z-]+)", text))
    check("no flag documented that the script does not have",
          sorted(documented - real_flags), [])

    print("every number the prose quotes is the number the script prints")
    import ipsae  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        pdb, cif, pae_path, _npz = ipsae._fixture_files(tmp)
        matrix = ipsae.load_pae(pae_path)
        residues = ipsae.load_residues(pdb)
        blind = ipsae.score_complex(matrix, residues, pae_cutoff=10.0, contact_distance=5.0)
        pairs = {frozenset((p["chain_a"], p["chain_b"])): p for p in blind["pairs"]}
        hl = pairs[frozenset(("H", "L"))]["ipsae"]
        hg = pairs[frozenset(("H", "G"))]["ipsae"]
        lg = pairs[frozenset(("L", "G"))]["ipsae"]
        check("the VH-VL figure in the prose", f"{hl:.4f}", "0.2835")
        check("...is quoted in SKILL.md", f"{hl:.4f}" in text, True)
        check("the paratope figure in the prose", f"{hg:.4f}", "0.0421")
        check("...is quoted in SKILL.md", f"{hg:.4f}" in text, True)
        check("the third pair really is zero", lg, 0.0)
        check("the ratio in the prose", f"{hl / hg:.1f}x", "6.7x")
        check("...is quoted in SKILL.md", f"{round(hl / hg, 1)}x" in text, True)

        # Every status named in the prose must be one the script can actually produce.
        # `no_qualifying_pairs` needs chains that touch but never clear the cutoff, which the
        # stock fixture does not contain -- so build it, rather than document a state by faith.
        touching_but_unconfident = matrix.copy()
        h, g = slice(0, 30), slice(60, 100)
        touching_but_unconfident[h, g] = 40.0
        touching_but_unconfident[g, h] = 40.0
        forced = ipsae.score_complex(touching_but_unconfident, residues, pae_cutoff=10.0,
                                     contact_distance=5.0, binder_chains=["H"],
                                     target_chains=["G"])["pairs"][0]
        produced = {"ok", "no_contacts", forced["status"]}
        check("the fixture produces no_qualifying_pairs on demand",
              forced["status"], "no_qualifying_pairs")
        check("and it is in contact while doing so", forced["min_interchain_distance"], 4.5)
        for status in ("ok", "no_qualifying_pairs", "no_contacts"):
            check(f"status {status!r} is documented", f"`{status}`" in text, True)
            check(f"status {status!r} is reachable", status in produced, True)

    print("the platform artifact the prose names is one the script actually eats")
    # `pae_<stem>.npz` beside `<stem>.cif`, one square array under the key "pae". If the
    # deployment ever renames either, this fails here rather than in someone's session.
    # This used to assert a `pae_<stem>.npz` companion was documented. That contract came
    # from Geodesic-Bio-Agent's cockpit, which is no longer in the image, and no job on the
    # deployment emits such a file -- so the guard was pinning a claim that was false.
    check("does not promise a companion file the deployment never writes",
          "pae_<stem>.npz" in text, False)
    check("says what a completed job actually returns", "results_overview.pdf" in text, True)
    check("and that a scalar pae is not a matrix", '"pae":9.676' in text, True)
    # This guard used to read `"unknown**, not cleared" in text` under the label
    # "protenix/esmfold are left unknown". When protenix was later cleared, that substring
    # survived -- it now describes esmfold alone -- so the check kept passing while the
    # claim it named had changed. A guard that greps a fragment shared by the old and new
    # wording cannot tell them apart. Pin both halves separately instead.
    flat = " ".join(text.split())
    check("esmfold is left unknown, not cleared",
          "`esmfold` is **unknown**, not cleared" in flat, True)
    check("protenix is no longer lumped in with it",
          "`protenix` and `esmfold` are **unknown**" in flat, False)
    check("protenix is recorded as cleared negative", "cleared negative" in flat, True)
    check("with the evidence, not just the verdict", "no PAE matrix" in flat, True)
    check("and the one-run caveat is kept", "one run, in one mode" in flat, True)
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _pdb, cif, pae_json, _npz = ipsae._fixture_files(tmp)
        import numpy as np  # noqa: PLC0415
        matrix = ipsae.load_pae(pae_json)
        companion = cif.with_name(f"pae_{cif.stem}.npz")
        np.savez(companion, pae=matrix.astype(np.float64))
        run = subprocess.run(
            [sys.executable, str(SCRIPT), "--pae", str(companion), "--structure", str(cif),
             "--binder-chains", "H,L", "--target-chains", "G"],
            capture_output=True, text=True)
        check("the companion loads with no conversion", run.returncode, 0)
        check("and scores the interface the prose names",
              json.loads(run.stdout)["best_cross_interface"]["chain_pair"], "H-G")

    print("the selftest count in the prose is the real one")
    out = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                         capture_output=True, text=True)
    count = out.stdout.count("PASS")
    check("selftest passes", out.returncode, 0)
    check("selftest check count is quoted correctly", f"{count} checks" in text, True)
    check("...and in the bash comment too", f"{count} known answers" in text, True)

    print("d0 still matches the reference implementation it claims to match")
    # calc_d0_array from DunbrackLab/IPSAE ipsae.py (version 4, 2026-01-03), the function
    # behind the headline ipSAE column. Transcribed, not imported -- the point is agreement
    # with an outside definition, so it must not share code with the thing under test.
    def reference_d0(length):
        clamped = max(26.0, float(length))
        return max(1.0, 1.24 * (clamped - 15) ** (1.0 / 3.0) - 1.8)
    worst = max(abs(ipsae.d0(L) - reference_d0(L)) for L in range(1, 61))
    check("bit-identical for every length 1-60", worst, 0.0)
    check("the L=27 value the prose names", round(ipsae.d0(27), 4), 1.0389)
    check("...and the claim is made in SKILL.md", "calc_d0_array" in text, True)

    # The two skills describe the same quantity and drifted apart once already: the reading
    # skill said the score is "forced to zero when the closest inter-chain atoms exceed a
    # distance cutoff", which is false for the reference implementation and contradicts what
    # this one tells the model. A contradiction between two skills in the same prompt is worse
    # than either being silent, and nothing else in this repo compares them.
    sibling = SKILL_DIR.parent / "antibody-interface-metrics" / "SKILL.md"
    if sibling.is_file():
        print("the sibling skill does not contradict this one")
        s = sibling.read_text()
        check("no distance-zeroing claim", "forced to zero when the closest" in s, False)
        # Target the CLAIM, not the digits: the corrected text legitimately mentions the old
        # values in a "these numbers used to read ..." note, and a check that forbids the
        # characters forbids explaining the correction.
        for stale in ("is **1.04 Å**", "0.041 under ipSAE", "pinned at ~1.04 Å", "a 15x gap",
                      "# floored at L = 27"):
            check(f"no longer asserts {stale!r}", stale in s, False)
        for value, label in (("6.67", "ipTM d0"), ("0.640", "ipTM score"),
                             ("1.00 Å", "per-residue d0"), ("0.038", "ipSAE score")):
            check(f"worked example still quotes {label} = {value}", value in s, True)
        # and the values it quotes must be the ones this script's d0 actually produces
        import math  # noqa: PLC0415
        d0_iptm = ipsae.d0(125 + 209)
        check("...and 6.67 is what d0(334) really is", round(d0_iptm, 2), 6.67)
        check("...and 1.00 is what d0(12) really is", round(ipsae.d0(12), 2), 1.0)
        check("...and 0.038 is the score that follows",
              round(1 / (1 + (5 / ipsae.d0(12)) ** 2), 3), 0.038)
        check("...and 0.640 is ipTM's",
              round(1 / (1 + (5 / d0_iptm) ** 2), 3), 0.64)

        # The dynamic-range section: its arithmetic must hold, not just its prose. A contact
        # term is -log(clip(p, 1e-8, 1)), so the clamp alone fixes the ceiling, and that
        # ceiling is what makes a 0.1-weighted term outrank a 1.0-weighted bounded one.
        flat_s = " ".join(s.split())
        check("the section is present",
              "dynamic range, not its weight, decides" in flat_s, True)
        check("the contact ceiling is the clamp's",
              round(-math.log(1e-8), 2), 18.42)
        check("...and the prose quotes it", "18.42" in flat_s, True)
        check("a 0.1-weighted contact term outspans a 1.0-weighted bounded one",
              round(0.1 * -math.log(1e-8), 2) > 1.0 * 1.0, True)
        check("...and the prose quotes that span", "1.84" in flat_s, True)
        check("the PAE term's weighted span is quoted",
              round(0.5 * 31, 2), 15.5)
        check("...and appears in the table", "15.50" in flat_s, True)
        check("the ratio singularity is quoted", "3.4e10" in flat_s, True)
    else:
        print("  SKIP  sibling-skill consistency: antibody-interface-metrics not installed here")

    print("repo hygiene")
    # The README forbids home paths and usernames in tracked files. The needles are built
    # rather than written, because a literal here would make this file fail its own check --
    # which is exactly what happened the first time it ran.
    needles = ["/" + "Users" + "/", "/" + "home" + "/"]
    # `getpass.getuser()` consults LOGNAME/USER/LNAME/USERNAME and then falls back to the
    # passwd database -- which RAISES for a uid that has no entry. That is the normal case
    # in the deployment's container, which runs as a bare numeric uid, and it took this
    # test crashing there to find out: the whole run aborted on a hygiene check.
    try:
        needles.append(getpass.getuser())
    except Exception:
        print("  note: no username available here, checking paths only "
              "(a bare uid with no passwd entry -- normal in a container)")
    for path in (SKILL_MD, SCRIPT, Path(__file__)):
        blob = path.read_text()
        hits = sorted(n for n in needles if n in blob)
        check(f"no home paths or usernames in {path.name}", hits, [])

    print("\n" + ("skill test passed" if _ok else "SKILL TEST FAILED"))
    return 0 if _ok else 1


if __name__ == "__main__":
    sys.exit(main())
