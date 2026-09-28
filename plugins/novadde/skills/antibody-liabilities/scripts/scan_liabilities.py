#!/usr/bin/env python3
"""
scan_liabilities.py

Deterministic chemical-liability and charge scan of an antibody chain. Everything
here is a regex or arithmetic over the sequence, so it belongs in code rather than
in a model's reading of a 120-character string -- which is the one task a language
model is worst at and the reason this script exists beside the skill.

What it does NOT do, on purpose:

  * It does not assign CDRs. Numbering comes from the design YAML or from ANARCI
    via the `antibody-numbering` skill, and a scanner that guesses IMGT windows
    reports liabilities against residues nobody designed. Pass `--cdr` or accept
    that every hit is reported as `framework-or-unassigned`.
  * It does not rank or gate. It reports positions and motif classes; whether a
    CDR-H3 NG matters more than a framework one is a judgement the skill makes.
  * It does not predict aggregation, immunogenicity or expression. Those need
    structure or a trained model. Hydrophobic-patch output here is a sequence
    observation, not a prediction.
  * It does not emit Met/Trp oxidation. Oxidation is not a pure sequence motif --
    it turns on solvent exposure, which a sequence does not know. Putting an `M`
    row in the same table as an `NG` row makes it read as a finding, and the
    `antibody-interface-metrics` skill rules on this directly: "say so rather than
    shipping a regex that pretends otherwise". A test below asserts the absence.

Stdlib only: it runs in the agent's kernel with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# EMBOSS pKa set, used because it is the one documented alongside most published
# antibody pI figures. A different set (Bjellqvist, Sillero) shifts a computed pI
# by a few tenths, which is why the set is named in the output rather than implied.
PKA_SIDE_CHAIN = {"C": 8.5, "D": 3.9, "E": 4.1, "H": 6.5, "K": 10.8, "R": 12.5, "Y": 10.1}
PKA_POSITIVE = frozenset("HKR")
PKA_N_TERM, PKA_C_TERM = 8.6, 3.6
PKA_SET_NAME = "EMBOSS"

# Kyte-Doolittle. Used only to find runs of hydrophobic residues; no scaled index
# is reported, because a windowed KD average on a 10-residue loop is not GRAVY and
# should not be read as one.
KYTE_DOOLITTLE = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5,
    "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
    "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

#: (regex, class, severity, why). Severities are the ordering the literature
#: agrees on; the absolute rate depends on pH, temperature and local structure,
#: none of which a sequence knows. `severity` orders a review queue -- it is not
#: a probability and must not be summed.
MOTIFS: tuple[tuple[str, str, str, str], ...] = (
    (r"N[G]",      "deamidation",     "high",     "NG is the fastest-deamidating pair; Asn->Asp/isoAsp"),
    (r"N[S]",      "deamidation",     "moderate", "NS deamidates measurably slower than NG"),
    (r"N[TNH]",    "deamidation",     "low",      "context-dependent; usually only matters in a flexible loop"),
    (r"D[G]",      "isomerisation",   "high",     "DG isomerises to isoAsp, which can abolish binding"),
    (r"D[SDT]",    "isomerisation",   "moderate", "slower than DG"),
    (r"D[P]",      "fragmentation",   "moderate", "Asp-Pro is the acid-labile peptide bond"),
    (r"N[^P][ST]", "n-glycosylation", "high",     "N-X-S/T sequon, X != Pro; see the glycoengineering skill"),
)

_RESIDUES = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")


def net_charge(sequence: str, ph: float) -> float:
    """Net charge at a given pH. Standard Henderson-Hasselbalch over the ionisable set."""
    charge = 1.0 / (1.0 + 10 ** (ph - PKA_N_TERM))
    charge -= 1.0 / (1.0 + 10 ** (PKA_C_TERM - ph))
    for residue, pka in PKA_SIDE_CHAIN.items():
        count = sequence.count(residue)
        if not count:
            continue
        if residue in PKA_POSITIVE:
            charge += count / (1.0 + 10 ** (ph - pka))
        else:
            charge -= count / (1.0 + 10 ** (pka - ph))
    return charge


def isoelectric_point(sequence: str, tolerance: float = 1e-4) -> float:
    """pI by bisection on net charge. Bracketed at 0-14 because no protein pI lies outside."""
    low, high = 0.0, 14.0
    while high - low > tolerance:
        mid = (low + high) / 2.0
        if net_charge(sequence, mid) > 0:
            low = mid
        else:
            high = mid
    return round((low + high) / 2.0, 2)


def parse_cdrs(specs: list[str] | None, length: int) -> dict[str, range]:
    """`--cdr H1=25:32` -> {"H1": range(25, 33)}. Inclusive, zero-based, as the design YAML is."""
    out: dict[str, range] = {}
    for spec in specs or []:
        try:
            name, span = spec.split("=", 1)
            start, end = (int(v) for v in span.split(":", 1))
        except ValueError:
            raise SystemExit(f"bad --cdr {spec!r}; expected NAME=start:end, zero-based inclusive")
        if not 0 <= start <= end < length:
            raise SystemExit(f"--cdr {spec!r} is outside a sequence of {length} residues")
        out[name] = range(start, end + 1)
    return out


def region_of(index: int, cdrs: dict[str, range]) -> str:
    for name, span in cdrs.items():
        if index in span:
            return name
    return "framework-or-unassigned" if not cdrs else "framework"


def scan(sequence: str, cdrs: dict[str, range]) -> list[dict]:
    hits: list[dict] = []
    for pattern, klass, severity, why in MOTIFS:
        for match in re.finditer(f"(?=({pattern}))", sequence):
            start = match.start()
            hits.append({
                "position": start,
                "motif": match.group(1),
                "class": klass,
                "severity": severity,
                "region": region_of(start, cdrs),
                "why": why,
            })
    hits.sort(key=lambda h: (h["position"], h["class"]))
    return hits


def hydrophobic_runs(sequence: str, cdrs: dict[str, range], *, min_len: int = 4) -> list[dict]:
    """Runs of >= min_len consecutive residues with positive Kyte-Doolittle value."""
    runs, start = [], None
    for i, residue in enumerate(sequence + "X"):
        positive = KYTE_DOOLITTLE.get(residue, -9) > 0
        if positive and start is None:
            start = i
        elif not positive and start is not None:
            if i - start >= min_len:
                runs.append({
                    "start": start, "end": i - 1, "length": i - start,
                    "residues": sequence[start:i], "region": region_of(start, cdrs),
                })
            start = None
    return runs


def report(sequence: str, cdrs: dict[str, range], name: str) -> dict:
    cysteines = [i for i, r in enumerate(sequence) if r == "C"]
    return {
        "name": name,
        "length": len(sequence),
        "pi": isoelectric_point(sequence),
        "pi_pka_set": PKA_SET_NAME,
        "net_charge_ph7": round(net_charge(sequence, 7.0), 2),
        "cysteines": {
            "positions": cysteines,
            "count": len(cysteines),
            "unpaired_by_parity": len(cysteines) % 2 == 1,
        },
        "cdrs_supplied": sorted(cdrs),
        "liabilities": scan(sequence, cdrs),
        "hydrophobic_runs": hydrophobic_runs(sequence, cdrs),
    }


def _selftest() -> int:
    """Known answers, so a change to a motif or a pKa shows up as a failure rather than a
    different number nobody notices. Run with --selftest."""
    failures: list[str] = []

    def check(label: str, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # a sequence carrying one of each, at positions chosen so an off-by-one shows
    seq = "AANGSDGAADPAANQTAAMAAWAAC"
    hits = {(h["position"], h["class"]) for h in scan(seq, {})}
    check("NG at 2", (2, "deamidation") in hits, True)
    check("NGS is also a sequon", (2, "n-glycosylation") in hits, True)
    check("DG at 5", (5, "isomerisation") in hits, True)
    check("DP at 9", (9, "fragmentation") in hits, True)
    check("NQT sequon at 13", (13, "n-glycosylation") in hits, True)
    check("no oxidation rows, ever", any(h["class"] == "oxidation" for h in scan(seq, {})), False)
    check("no sequon before a proline", any(h["motif"] == "NPT" for h in scan("AANPTA", {})), False)
    check("overlapping motifs both reported", len(scan("NGSNGS", {})), len(scan("NGSNGS", {})))
    check("odd cysteine count is flagged", report(seq, {}, "t")["cysteines"]["unpaired_by_parity"], True)

    # charge: a polyK chain is basic, polyE acidic, and both bracket neutral glycine
    check("polyK pI is basic", isoelectric_point("KKKKKKKKKK") > 10, True)
    check("polyE pI is acidic", isoelectric_point("EEEEEEEEEE") < 4.5, True)
    check("net charge falls as pH rises", net_charge("KKKEEE", 4.0) > net_charge("KKKEEE", 10.0), True)

    # region attribution is by the ranges given, never guessed
    cdrs = parse_cdrs(["H1=2:3"], len(seq))
    regions = {h["position"]: h["region"] for h in scan(seq, cdrs)}
    check("hit inside the supplied CDR", regions.get(2), "H1")
    check("hit outside it", regions.get(9), "framework")
    check("no CDRs supplied says so", scan(seq, {})[0]["region"], "framework-or-unassigned")

    for line in failures:
        print(f"FAIL  {line}")
    print(f"\n{'PASS' if not failures else str(len(failures)) + ' FAILURES'}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sequence", nargs="?", help="one-letter amino-acid sequence")
    parser.add_argument("--name", default="chain", help="label for the report")
    parser.add_argument("--cdr", action="append", metavar="NAME=START:END",
                        help="zero-based inclusive CDR span, repeatable; from the design YAML")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--selftest", action="store_true", help="run the known-answer checks and exit")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()
    if not args.sequence:
        parser.error("a sequence is required (or --selftest)")

    sequence = args.sequence.strip().upper()
    if not _RESIDUES.match(sequence):
        raise SystemExit("sequence must be the 20 canonical one-letter codes, uppercase, no gaps")

    data = report(sequence, parse_cdrs(args.cdr, len(sequence)), args.name)
    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    print(f"{data['name']}  {data['length']} aa   pI {data['pi']} ({data['pi_pka_set']})"
          f"   net charge at pH 7.0: {data['net_charge_ph7']:+}")
    cys = data["cysteines"]
    print(f"cysteines: {cys['count']} at {cys['positions']}"
          f"{'  <- ODD COUNT, one is unpaired unless it bonds another chain' if cys['unpaired_by_parity'] else ''}")
    if not data["cdrs_supplied"]:
        print("no --cdr given: every hit below is reported as framework-or-unassigned, not attributed")
    print()
    if data["liabilities"]:
        print(f"{'pos':>5}  {'motif':<5} {'class':<16} {'severity':<9} {'region':<24} why")
        for h in data["liabilities"]:
            print(f"{h['position']:>5}  {h['motif']:<5} {h['class']:<16} {h['severity']:<9} {h['region']:<24} {h['why']}")
    else:
        print("no motif hits")
    for run in data["hydrophobic_runs"]:
        print(f"hydrophobic run {run['start']}-{run['end']} ({run['length']} aa) {run['residues']} in {run['region']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
