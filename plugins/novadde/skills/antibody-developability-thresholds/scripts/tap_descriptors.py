#!/usr/bin/env python3
"""Total CDR length against TAP's clinical-stage thresholds, and a refusal for the other four.

TAP (Raybould et al., PNAS 2019 116:4025; TAP2, Commun Biol 2024) reports five descriptors
against the distribution of clinical-stage therapeutics (CSTs). Exactly ONE of them is
computable from sequence:

    Total CDR length   IMGT numbering only                      <- this script
    PSH                surface hydrophobicity patches           needs a 3D Fv model
    PPC / PNC          surface charge patches                   needs a 3D Fv model
    SFvCSP             net VH charge x net VL charge, but ONLY over surface-exposed,
                       non-salt-bridged residues                needs a 3D Fv model

SFvCSP is the trap. It looks sequence-computable and is not: the "S" is for *structural*,
and the sequence-level cousin (FvCSP, Sharma et al.) is a different metric with different
values -- the paper's own galiximab example is FvCSP 0 against SFvCSP +2.0. Computing a
net-charge product from sequence and calling it SFvCSP would produce a number that gets
compared against TAP's SFvCSP thresholds and is not the same quantity.

So this script computes total CDR length, flags it against a threshold set you must name,
and refuses the other four.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys

#: IMGT CDR spans TAP uses, stated in the TAP2 Methods. Here to be reported, not applied:
#: turning a sequence into IMGT positions needs ANARCI, which this script does not do.
IMGT_CDR_SPANS = {"1": "27-38", "2": "56-65", "3": "105-117"}

#: The vicinity the three patch metrics are summed over -- IMGT CDR residues +/-2 each side,
#: plus any other surface-exposed residue within 4.5 A (TAP2; the 2019 paper says 4 A, and
#: whether that is a real protocol change or a loose restatement is not established).
CDR_VICINITY = "IMGT CDR residues +/-2, plus surface-exposed residues within 4.5 A (TAP2)"

#: Total CDR length thresholds. THREE published sets, not interchangeable -- OPIG warns
#: explicitly against comparing scores across modelling versions, and the reference set and
#: the structure predictor both changed between them.
#:
#: "amber" is the 0-5th or 95-100th percentile of the CST set. "red" is NOT a percentile: it
#: means outside the entire observed range of that set. So the outer amber bound and the red
#: bound are the same number, which is the invariant --selftest checks.
THRESHOLDS = {
    "2019": {
        "source": "Raybould et al., PNAS 2019 116(10):4025, Table 2",
        "reference_set": "242 clinical-stage therapeutics, ABodyBuilder1 models",
        "amber_low": None,  # not published -- see the note below
        "amber_high": (54, 60),
        "red_high": 60,
        "caveat": "Table 1 says total CDR length flags bottom 5% AND top 5%, but Table 2 "
                  "prints no lower region, and neither does SI Table S3 or S4. The 2019 "
                  "lower bound is not published. This script will not invent one.",
    },
    "tap2-2024": {
        "source": "Raybould et al., Commun Biol 2024, Table 1 (ABodyBuilder2 column)",
        "reference_set": "664 non-redundant CST Fvs, ABodyBuilder2/ImmuneBuilder models",
        "amber_low": (37, 42),
        "amber_high": (55, 63),
        "red_low": 37,
        "red_high": 63,
        "caveat": "",
    },
    "live-2025": {
        "source": "TAP web tool threshold table, dated 2025-02-24",
        "reference_set": "851 post-Phase-I therapeutic Fvs",
        "amber_low": (37, 42),
        "amber_high": (55, 65),
        "red_low": 37,
        "red_high": 65,
        "caveat": "What the deployed tool applies today. Its PPC and PNC rows are "
                  "internally inconsistent (amber-outer != red), but total CDR length is "
                  "not affected.",
    },
}

#: The four descriptors this script will not compute, and why each needs a structure.
NEEDS_A_STRUCTURE = {
    "PSH": "hydrophobicity-weighted sum over surface-exposed residue pairs within 7.5 A of "
           "the CDR vicinity, Kyte-Doolittle linearly normalised to [1,2], kernel 1/r^2",
    "PPC": "the same kernel with |Q(R)| substituted for hydrophobicity, positive residues",
    "PNC": "the same, negative residues",
    "SFvCSP": "net VH charge x net VL charge, summed ONLY over surface-exposed, "
              "non-salt-bridged residues across the whole Fv surface. NOT the "
              "sequence-level FvCSP of Sharma et al., which is a different number.",
}

CDR_NAMES = ("H1", "H2", "H3", "L1", "L2", "L3")


def parse_lengths(spec: str) -> dict[str, int]:
    """`H1=8,H2=8,H3=13,L1=6,L2=3,L3=9` -> dict. Lengths, not windows: the spans TAP uses
    are IMGT *numbering* positions, so a sequence index range cannot express them."""
    out: dict[str, int] = {}
    for item in filter(None, (s.strip() for s in spec.split(","))):
        try:
            name, value = item.split("=", 1)
            out[name.strip().upper()] = int(value)
        except ValueError:
            raise SystemExit(f"error: cannot parse {item!r}; want H1=8") from None
    return out


def total_cdr_length(lengths: dict[str, int], thresholds: str) -> dict:
    """Sum the six IMGT CDR lengths and flag the total.

    All six are required. The 2019 paper never enumerates which CDRs the total covers, but
    its reported mean of 48.02 +/- 3.77 over 242 CSTs is only reachable with all six, so a
    partial total would be compared against a threshold built from a different quantity.
    """
    if thresholds not in THRESHOLDS:
        raise SystemExit(f"error: unknown threshold set {thresholds!r}; "
                         f"choose one of {sorted(THRESHOLDS)}")
    missing = [c for c in CDR_NAMES if c not in lengths]
    if missing:
        raise SystemExit(
            f"error: total CDR length needs all six CDRs; missing {', '.join(missing)}. "
            "TAP's total is over H1-H3 and L1-L3, so a partial sum is not comparable with "
            "its thresholds."
        )
    unknown = sorted(set(lengths) - set(CDR_NAMES))
    if unknown:
        raise SystemExit(f"error: {unknown} are not CDR names; expected {list(CDR_NAMES)}")
    if any(v < 0 for v in lengths.values()):
        raise SystemExit("error: a CDR length cannot be negative")

    spec = THRESHOLDS[thresholds]
    total = sum(lengths[c] for c in CDR_NAMES)

    flag, why = "green", "inside the clinical-stage distribution"
    red_low, red_high = spec.get("red_low"), spec.get("red_high")
    if red_high is not None and total > red_high:
        flag, why = "red", f"above the whole observed CST range (> {red_high})"
    elif red_low is not None and total < red_low:
        flag, why = "red", f"below the whole observed CST range (< {red_low})"
    else:
        for band in (spec.get("amber_low"), spec.get("amber_high")):
            if band and band[0] <= total <= band[1]:
                flag, why = "amber", f"in the outer 5% of the CST distribution ({band[0]}-{band[1]})"
                break

    out = {
        "total_cdr_length": total,
        "per_cdr": {c: lengths[c] for c in CDR_NAMES},
        "flag": flag,
        "why": why,
        "threshold_set": thresholds,
        "source": spec["source"],
        "reference_set": spec["reference_set"],
        "numbering_required": "IMGT",
        "imgt_cdr_spans": IMGT_CDR_SPANS,
    }
    if spec.get("caveat"):
        out["caveat"] = spec["caveat"]
    if thresholds == "2019" and total < 54:
        out["note_low_end"] = ("The 2019 set publishes no lower bound, so a low total is "
                               "unflagged here rather than green. Use tap2-2024 or "
                               "live-2025 if the low end matters.")
    return out


def refused() -> dict:
    """The four descriptors this script will not approximate."""
    return {
        name: {
            "status": "needs_a_structure",
            "definition": what,
            "vicinity": CDR_VICINITY if name != "SFvCSP" else "the whole Fv surface",
            "how_to_get_it": "run TAP itself -- it builds the Fv model for you from the two "
                             "sequences (ABodyBuilder2/ImmuneBuilder since 2023-01-30)",
        }
        for name, what in NEEDS_A_STRUCTURE.items()
    }


def _selftest() -> int:
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    print("the threshold sets are internally consistent")
    # "red" means outside the observed range, so the outer amber bound and the red bound must
    # be the same number. This is the check that catches a mistranscribed threshold.
    for name in ("tap2-2024", "live-2025"):
        s = THRESHOLDS[name]
        check(f"{name}: amber_high outer == red_high", s["amber_high"][1], s["red_high"])
        check(f"{name}: amber_low outer == red_low", s["amber_low"][0], s["red_low"])
    check("2019 publishes no lower bound", THRESHOLDS["2019"]["amber_low"], None)
    check("2019: amber_high outer == red_high",
          THRESHOLDS["2019"]["amber_high"][1], THRESHOLDS["2019"]["red_high"])

    print("flagging, against tap2-2024 (37-42 amber, 43-54 green, 55-63 amber, outside red)")
    six = lambda n: {c: v for c, v in zip(CDR_NAMES, n)}  # noqa: E731
    check("48 is green", total_cdr_length(six([8, 8, 13, 6, 3, 10]), "tap2-2024")["flag"], "green")
    check("total is the sum", total_cdr_length(six([8, 8, 13, 6, 3, 10]), "tap2-2024")["total_cdr_length"], 48)
    check("63 is amber, not red", total_cdr_length(six([13, 13, 15, 8, 4, 10]), "tap2-2024")["flag"], "amber")
    check("64 is red", total_cdr_length(six([13, 13, 16, 8, 4, 10]), "tap2-2024")["flag"], "red")
    check("37 is amber", total_cdr_length(six([6, 6, 10, 5, 3, 7]), "tap2-2024")["flag"], "amber")
    check("36 is red", total_cdr_length(six([6, 6, 9, 5, 3, 7]), "tap2-2024")["flag"], "red")

    print("the three sets disagree, and that is the point")
    long_one = six([13, 13, 16, 8, 4, 10])  # 64
    check("64 is red under tap2-2024", total_cdr_length(long_one, "tap2-2024")["flag"], "red")
    check("...and amber under live-2025", total_cdr_length(long_one, "live-2025")["flag"], "amber")
    check("...and red under 2019", total_cdr_length(long_one, "2019")["flag"], "red")

    print("refusals")
    r = refused()
    check("four refused, including SFvCSP", sorted(r), ["PNC", "PPC", "PSH", "SFvCSP"])
    check("none carries a number", any("value" in v or "score" in v for v in r.values()), False)
    check("SFvCSP says it is not FvCSP", "FvCSP" in r["SFvCSP"]["definition"], True)

    print("refusals of bad input")
    for spec, why in ((("H1=8,H2=8"), "all six"), ("H1=8,H2=8,H3=13,L1=6,L2=3,X9=1", "not CDR names")):
        try:
            total_cdr_length(parse_lengths(spec), "tap2-2024")
        except SystemExit as exc:
            check(f"refuses input: {why}", why.split()[0] in str(exc), True)
        else:
            check(f"refuses input: {why}", "no refusal", "SystemExit")
    try:
        total_cdr_length(parse_lengths("H1=8,H2=8,H3=13,L1=6,L2=3,L3=9"), "made-up")
    except SystemExit as exc:
        check("refuses an unknown threshold set", "unknown threshold set" in str(exc), True)

    print("\n" + ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Total CDR length against TAP's CST thresholds.")
    p.add_argument("--cdr-lengths", help="H1=8,H2=8,H3=13,L1=6,L2=3,L3=9 -- IMGT CDR lengths, "
                                         "all six required")
    p.add_argument("--thresholds", default="tap2-2024", choices=sorted(THRESHOLDS),
                   help="which published threshold set to flag against (default: tap2-2024)")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        return _selftest()
    if not args.cdr_lengths:
        p.error("--cdr-lengths is required (or use --selftest)")
    report = total_cdr_length(parse_lengths(args.cdr_lengths), args.thresholds)
    report["not_computed"] = refused()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
