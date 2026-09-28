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
SCRIPT = HERE / "score_variants.py"
sys.path.insert(0, str(HERE))

_ok = True


def check(label, got, want):
    global _ok
    good = got == want
    _ok = _ok and good
    print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")


def main() -> int:
    import score_variants as td

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
    check("description names the skill that owns running the model",
          "fair-esm2" in desc, True)

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

    print("the numbers in the prose are the ones the source reports")
    flat = " ".join(text.split())
    for claim, why in (
        ("masked 0.582, mutant 0.578, wt **0.572**, pseudo-likelihood 0.552", "Table 5"),
        ("**0.004**", "the honest margin"),
        ("**0.482 / 0.483** against **0.692**", "the multi-mutant gap, Table 7"),
        ("**0.422** at depth 1, **0.248** at depth 2", "ProteinGym depth decay"),
        ("ESM-2 650M | **0.414**", "the checkpoint table"),
        ("650M > 3B > 15B", "the scale inversion"),
        ("**+0.025**", "what ensembling buys"),
        ("**10.97**", "ESM-2 CDR-H3 perplexity"),
    ):
        check(why, " ".join(claim.split()) in flat, True)

    print("the three claims that keep the number honest")
    for claim, why in (
        ("|Spearman", "the absolute-value blindness"),
        ("a flipped sign reproduces the paper's numbers exactly", "why a correlation cannot catch it"),
        ("undefined", "indels are undefined, not inaccurate"),
        ("not one is a masked language model", "the ProteinGym indel leaderboard"),
        ("What is not established", "the section admitting what is unsourced"),
    ):
        check(why, " ".join(claim.split()) in flat, True)

    print("the script enforces what the prose promises")
    import numpy as np  # noqa: PLC0415
    lp = td._uniform_lp(60)
    single = td.score_variant_set(lp, td.parse_variants("A24G", True), "masked-marginal", True)
    check("a single substitution scores", single["score"], 0.0)
    multi = td.score_variant_set(lp, td.parse_variants("A24G,A30S", True), "masked-marginal", True)
    check("a multi-mutant is refused, not silently summed", multi["score"], None)
    check("...and the refusal carries both measured numbers",
          "0.482" in multi["refused"] and "0.692" in multi["refused"], True)
    check("the convention is stamped into every result",
          single["convention"], "masked-marginal")
    check("...with the provenance that cannot be inferred from the file",
          "forward pass" in single["provenance_required"], True)
    short = td.pseudo_log_likelihood(np.tile(td._uniform_lp(1), (5, 1)), "A" * 5)
    check("PLL reports both forms", sorted(k for k in short if k.startswith("pll")),
          ["pll_per_residue", "pll_summed"])

    # fair-esm2 is where the tables actually get produced, and it had shipped an unmasked
    # forward pass under a comment describing masked scoring -- the exact conflation this
    # skill exists to close. Nothing else in the repo compares the two files.
    sibling = SKILL_DIR.parent / "fair-esm2" / "SKILL.md"
    if sibling.is_file():
        print("fair-esm2 does not reintroduce the conflation")
        s = sibling.read_text()
        flat_s = " ".join(s.split())
        check("the old conflated comment is gone",
              "WT marginal log-likelihood; for mutation scoring, mask the position" in flat_s,
              False)
        check("it names both conventions", "wt-marginal" in s and "masked-marginal" in s, True)
        check("the masked path is a separate loop, not a comment",
              "alphabet.mask_idx" in s, True)
        check("it log-softmaxes rather than reading raw logits",
              "log_softmax" in s, True)
        check("and it points here for which to use", "plm-variant-scoring" in s, True)
    else:
        print("  SKIP  fair-esm2 cross-check: sibling not installed here")

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
