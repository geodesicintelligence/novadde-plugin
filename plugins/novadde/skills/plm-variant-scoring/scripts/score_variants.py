#!/usr/bin/env python3
"""Score protein variants from a language model's log-probabilities, under a named convention.

The reason this exists: two of the common conventions consume an IDENTICALLY SHAPED (L x 20)
matrix and differ only in how it was produced.

    wt-marginal       ONE forward pass over the wild-type sequence, nothing masked.
                      Row i is the distribution at position i with every residue visible.
    masked-marginal   L forward passes. Row i comes from the pass where position i -- and only
                      position i -- was replaced with <mask>.

Nothing about the array distinguishes them. Same shape, same dtype, same plausible values. So
this script will not infer the convention: you declare it, it is stamped into the output, and
a score computed one way can never be silently compared with a score computed the other way.

Stdlib + numpy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

#: The 20 standard amino acids, in the column order this script expects.
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
AA_INDEX = {a: i for i, a in enumerate(AMINO_ACIDS)}

#: How each convention's matrix must have been produced. This is the part a file cannot tell
#: you, and the part that makes two numbers comparable or not.
PROVENANCE = {
    "wt-marginal": "one forward pass over the wild-type sequence, nothing masked; row i is the "
                   "distribution at position i with all residues visible",
    "masked-marginal": "L forward passes; row i is the distribution at position i from the pass "
                       "where position i alone was replaced with <mask>",
}

_VARIANT_RE = re.compile(r"^([A-Z])(\d+)([A-Z])$")


class InputError(RuntimeError):
    """Something about the inputs is wrong in a way guessing would not fix."""


def load_logprobs(path: Path) -> np.ndarray:
    """An (L, 20) matrix of LOG-probabilities, one row per position.

    Rejects raw logits: a row of log-probabilities sums to 1 after exponentiation, and a row
    of logits does not. Scoring a substitution from logits happens to give the same answer as
    from log-probs, because the log-softmax denominator cancels at a shared position -- but
    any whole-sequence sum does not survive that, so the distinction is enforced here rather
    than left to chance.
    """
    if path.suffix == ".npz":
        with np.load(path) as bundle:
            keys = [k for k in ("logprobs", "log_probs", "logits") if k in bundle]
            if len(keys) != 1:
                raise InputError(
                    f"{path.name}: expected exactly one of ['logprobs', 'log_probs', 'logits'], "
                    f"found {keys}"
                )
            if keys[0] == "logits":
                raise InputError(
                    f"{path.name} holds 'logits'. This script wants LOG-PROBABILITIES: apply "
                    "log_softmax over the amino-acid axis first. The difference cancels for a "
                    "single substitution and does not for anything summed over positions."
                )
            matrix = np.asarray(bundle[keys[0]], dtype=float)
    else:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or "logprobs" not in data:
            raise InputError(f"{path.name}: expected a JSON object with a 'logprobs' key")
        matrix = np.asarray(data["logprobs"], dtype=float)

    if matrix.ndim != 2 or matrix.shape[1] != len(AMINO_ACIDS):
        raise InputError(
            f"{path.name}: expected (L, 20) with columns in the order {AMINO_ACIDS}, "
            f"got shape {matrix.shape}"
        )
    if float(matrix.max()) > 0.0 + 1e-6:
        raise InputError(
            f"{path.name}: contains positive values (max {matrix.max():.3f}), so these are not "
            "log-probabilities. Apply log_softmax over the amino-acid axis."
        )
    total = np.exp(matrix).sum(axis=1)
    off = np.abs(total - 1.0).max()
    if off > 0.05:
        raise InputError(
            f"{path.name}: rows do not normalise -- worst row sums to {total[np.argmax(np.abs(total - 1.0))]:.3f} "
            "after exp(). Columns must be exactly the 20 standard amino acids, log-softmaxed "
            "over that axis. A row that includes special tokens will not sum to 1 here."
        )
    return matrix


def parse_variants(spec: str, one_based: bool) -> list[tuple[str, int, str]]:
    """`A24G,T57S` -> [('A', 24, 'G'), ('T', 57, 'S')], positions kept as written."""
    out = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        m = _VARIANT_RE.match(item)
        if not m:
            raise InputError(f"cannot parse variant {item!r}; want the form A24G")
        wt, pos, mut = m.group(1), int(m.group(2)), m.group(3)
        for aa, which in ((wt, "wild-type"), (mut, "mutant")):
            if aa not in AA_INDEX:
                raise InputError(f"{item}: {which} residue {aa!r} is not a standard amino acid")
        if one_based and pos < 1:
            raise InputError(f"{item}: position {pos} is not 1-based")
        out.append((wt, pos, mut))
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_substitution(lp: np.ndarray, wt: str, pos0: int, mut: str) -> float:
    """log p(mutant) - log p(wild-type) at one position.

    Sign: HIGHER means the model finds the mutant MORE likely. Every formula in Meier et al.
    Appendix A puts the mutant term first, and the reference `label_row` implements
    `token_probs[..., mt] - token_probs[..., wt]`.

    That direction is inferred from the formula, never asserted in the paper's prose -- and
    the paper's headline metric is |Spearman rho|, ABSOLUTE value, on every table. So a sign
    error in a pipeline is invisible to any correlation reproduced from that benchmark. Check
    the direction against a substitution you already know, not against a correlation.
    """
    if pos0 < 0 or pos0 >= lp.shape[0]:
        raise InputError(f"position {pos0 + 1} is outside the {lp.shape[0]}-residue matrix")
    return float(lp[pos0, AA_INDEX[mut]] - lp[pos0, AA_INDEX[wt]])


def score_variant_set(lp: np.ndarray, variants, convention: str, one_based: bool) -> dict:
    """Score one variant (possibly multi-mutant) under a declared convention.

    The refusal below is the point of this script. For a SINGLE substitution, a per-position
    masked table is exactly Meier's Strategy (a). For a MULTI-mutant it is not: Strategy (a)
    masks every mutated position SIMULTANEOUSLY, which needs its own forward pass per variant
    set. Re-using the per-position table instead gives Strategy (b)/(c) -- and on the paper's
    own PABP doubles set that is |Spearman rho| 0.482/0.483 against 0.692 for (a).

    The released reference implementation masks one position at a time and never splits a
    multi-mutant token, so extending it to doubles walks straight into the 0.482 case with
    nothing to indicate it.
    """
    if convention not in PROVENANCE:
        raise InputError(f"unknown convention {convention!r}; choose one of {sorted(PROVENANCE)}")

    terms = []
    for wt, pos, mut in variants:
        pos0 = pos - 1 if one_based else pos
        terms.append({
            "variant": f"{wt}{pos}{mut}",
            "score": round(score_substitution(lp, wt, pos0, mut), 6),
        })

    out = {
        "convention": convention,
        "provenance_required": PROVENANCE[convention],
        "n_mutations": len(terms),
        "per_mutation": terms,
        "score": round(sum(t["score"] for t in terms), 6),
        "sign": "higher = the model finds the mutant more likely",
        "model_additive": "Meier et al. assume an additive model over mutated positions, "
                          "asserted from the training objective rather than tested against a "
                          "non-additive alternative",
    }

    if len(terms) > 1 and convention == "masked-marginal":
        out["score"] = None
        out["refused"] = (
            "A per-position masked table cannot give Meier's Strategy (a) for a multi-mutant. "
            "(a) masks ALL mutated positions in one pass; reusing the per-position table is "
            "Strategy (b)/(c), which scores 0.482/0.483 against 0.692 for (a) on the paper's "
            "PABP doubles set. Supply a matrix from a pass masked at every mutated position, "
            "and declare it, or score the mutations singly and state that the sum is (b)/(c)."
        )
    if len(terms) > 1:
        out["depth_caveat"] = (
            "Zero-shot accuracy falls steeply with mutational depth. ProteinGym, 217 "
            "substitution assays, ESM-2 650M: 0.422 at depth 1, 0.248 at depth 2, 0.205 at "
            "depth 3, 0.163 at depth 4."
        )
    return out


def pseudo_log_likelihood(lp: np.ndarray, sequence: str) -> dict:
    """PLL = sum over ALL positions of log p(x_i | x_-i). A SUM, per Salazar et al. ACL 2020.

    Reported summed and per-residue, because the two rank differently and only one of them
    can be compared across lengths. Every term is a log probability and therefore negative,
    so a summed PLL grows more negative with length: comparing summed PLLs between sequences
    of different length ranks the SHORTER one higher, whatever its quality.

    Meier et al. never address this -- all 41 of its benchmarks hold length fixed, so the
    question cannot arise there. The length argument is arithmetic, not a citation.
    """
    if len(sequence) != lp.shape[0]:
        raise InputError(
            f"sequence is {len(sequence)} residues but the matrix has {lp.shape[0]} rows"
        )
    bad = sorted(set(sequence) - set(AMINO_ACIDS))
    if bad:
        raise InputError(f"sequence contains non-standard residues {bad}")
    per_position = [float(lp[i, AA_INDEX[a]]) for i, a in enumerate(sequence)]
    total = sum(per_position)
    return {
        "pll_summed": round(total, 6),
        "pll_per_residue": round(total / len(sequence), 6),
        "length": len(sequence),
        "comparable_across_lengths": "pll_per_residue only -- pll_summed is extensive and "
                                     "ranks shorter sequences higher",
    }


def _uniform_lp(rows: int) -> np.ndarray:
    """A properly normalised log-prob matrix where every residue is equally likely."""
    return np.full((rows, len(AMINO_ACIDS)), -np.log(len(AMINO_ACIDS)))


def _selftest() -> int:
    ok = True

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        good = abs(got - want) < tol if isinstance(want, float) else got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    print("sign convention -- the thing the benchmark cannot catch")
    # Meier et al. report |Spearman rho| on every table, so a flipped sign reproduces the
    # paper's numbers exactly. Only a known answer catches it.
    lp = _uniform_lp(10).copy()
    wt_i, mut_i = AA_INDEX["A"], AA_INDEX["G"]
    lp[4, mut_i] = np.log(0.5)            # G is likely here
    lp[4, wt_i] = np.log(0.01)            # A is not
    lp[4] = lp[4] - np.log(np.exp(lp[4]).sum())
    s = score_substitution(lp, "A", 4, "G")
    check("a mutation to a LIKELIER residue scores positive", s > 0, True)
    check("and the magnitude is the log-odds ratio",
          round(s, 6), round(float(lp[4, mut_i] - lp[4, wt_i]), 6))
    check("the reverse substitution is exactly its negative",
          round(score_substitution(lp, "G", 4, "A"), 6), round(-s, 6))
    check("a synonymous 'mutation' is zero", score_substitution(lp, "A", 4, "A"), 0.0)

    print("multi-mutants: the trap the reference implementation walks into")
    flat = _uniform_lp(60)
    one = score_variant_set(flat, parse_variants("A24G", True), "masked-marginal", True)
    check("a single substitution IS Strategy (a)", one["score"], 0.0)
    two = score_variant_set(flat, parse_variants("A24G,A30S", True), "masked-marginal", True)
    check("a multi-mutant is refused under masked-marginal", two["score"], None)
    check("...and the refusal quotes the measured cost", "0.482" in two["refused"], True)
    check("...and 0.692 as the alternative", "0.692" in two["refused"], True)
    wtm = score_variant_set(flat, parse_variants("A24G,A30S", True), "wt-marginal", True)
    check("wt-marginal sums additively without refusing", wtm["score"], 0.0)
    check("but carries the depth caveat", "depth 2" in wtm["depth_caveat"], True)

    print("provenance is declared, never inferred")
    check("two conventions, two provenances", sorted(PROVENANCE), ["masked-marginal", "wt-marginal"])
    check("the provenance is stamped into the output",
          one["provenance_required"], PROVENANCE["masked-marginal"])
    for conv in PROVENANCE:
        check(f"{conv} says how the matrix was produced",
              "forward pass" in PROVENANCE[conv], True)
    try:
        score_variant_set(flat, parse_variants("A24G", True), "made-up", True)
    except InputError as exc:
        check("an undeclared convention is refused", "unknown convention" in str(exc), True)

    print("pseudo-log-likelihood is a sum, and that is why length matters")
    seq10, seq30 = "A" * 10, "A" * 30
    # Identical per-residue quality, different lengths.
    p10 = pseudo_log_likelihood(_uniform_lp(10), seq10)
    p30 = pseudo_log_likelihood(_uniform_lp(30), seq30)
    check("per-residue is identical", p10["pll_per_residue"], p30["pll_per_residue"])
    check("summed is not", p10["pll_summed"] == p30["pll_summed"], False)
    check("and summed ranks the SHORTER one higher", p10["pll_summed"] > p30["pll_summed"], True)

    # The two statistics can DISAGREE, which is the failure worth demonstrating: summed PLL
    # conflates length with quality, so a short mediocre sequence can outrank a long good one.
    # (Summed does not ALWAYS favour the shorter sequence -- a large enough per-residue gap
    # overcomes the length term. The bias is a tilt, not a guarantee, and a test that claimed
    # otherwise would be wrong. This one failed on exactly that overstatement.)
    def _row(target_logp: float) -> np.ndarray:
        """One normalised row where residue A has exactly `target_logp`."""
        rest = (1.0 - np.exp(target_logp)) / (len(AMINO_ACIDS) - 1)
        row = np.full(len(AMINO_ACIDS), np.log(rest))
        row[AA_INDEX["A"]] = target_logp
        return row

    short_lp = np.tile(_row(-1.00), (5, 1))     # 5 residues, -1.00 each  -> summed  -5.0
    long_lp = np.tile(_row(-0.90), (50, 1))     # 50 residues, -0.90 each -> summed -45.0
    short = pseudo_log_likelihood(short_lp, "A" * 5)
    long_ = pseudo_log_likelihood(long_lp, "A" * 50)
    check("the long sequence is better per residue",
          long_["pll_per_residue"] > short["pll_per_residue"], True)
    check("...but summed ranks the short one above it",
          short["pll_summed"] > long_["pll_summed"], True)
    check("so the two statistics disagree on the same pair",
          (long_["pll_per_residue"] > short["pll_per_residue"])
          != (long_["pll_summed"] > short["pll_summed"]), True)

    print("input refusals")
    check("a sequence of the wrong length is refused",
          _raises(lambda: pseudo_log_likelihood(_uniform_lp(10), "A" * 9), "residues but"), True)
    check("a non-standard residue is refused",
          _raises(lambda: pseudo_log_likelihood(_uniform_lp(3), "AXA"), "non-standard"), True)
    check("an out-of-range position is refused",
          _raises(lambda: score_substitution(_uniform_lp(5), "A", 99, "G"), "outside"), True)

    print("\n" + ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def _raises(fn, needle: str) -> bool:
    try:
        fn()
    except InputError as exc:
        return needle in str(exc)
    return False


def main() -> int:
    p = argparse.ArgumentParser(description="Score variants from PLM log-probabilities.")
    p.add_argument("--logprobs", type=Path, help="(L, 20) log-probabilities, .npz or .json")
    p.add_argument("--convention", choices=sorted(PROVENANCE),
                   help="REQUIRED with --logprobs: how that matrix was produced. Not inferable.")
    p.add_argument("--variants", help="A24G or A24G,T57S for a multi-mutant")
    p.add_argument("--sequence", help="score this sequence's pseudo-log-likelihood instead")
    p.add_argument("--zero-based", action="store_true", help="positions are 0-based (default 1)")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        return _selftest()
    if not args.logprobs:
        p.error("--logprobs is required (or use --selftest)")
    if not args.convention and not args.sequence:
        p.error("--convention is required: wt-marginal and masked-marginal take an "
                "identically shaped matrix and differ only in how it was produced, so this "
                "cannot be inferred from the file")
    try:
        lp = load_logprobs(args.logprobs)
        if args.sequence:
            report = pseudo_log_likelihood(lp, args.sequence)
            report["convention"] = "pseudo-log-likelihood"
        else:
            if not args.variants:
                p.error("--variants is required unless --sequence is given")
            report = score_variant_set(
                lp, parse_variants(args.variants, not args.zero_based),
                args.convention, not args.zero_based)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report["inputs"] = {"logprobs": str(args.logprobs), "sha256": sha256(args.logprobs)}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
