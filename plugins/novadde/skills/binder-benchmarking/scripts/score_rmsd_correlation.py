#!/usr/bin/env python3
"""
score_rmsd_correlation.py

Implements the "Gate: does the model's own score track RMSD?" check from the
binder-benchmarking skill. Given a per-design table with the model's own
ranking score and its RMSD to the best-matching known positive, it reports:

  1. Spearman rank correlation between score and RMSD over the full pool.
  2. Top-K enrichment: what fraction of the near-native subset (RMSD at or
     below your cutoff, and — ideally — hitting the known anchor residues /
     motif) falls inside the model's own top-K by score, versus the K/N
     you'd expect by chance.

Read the result as a gate, not a grade: strong correlation / enrichment means
the model's self-score is trustworthy for blind triage on new targets; weak
or absent correlation means keep a structural re-ranking or orthogonal filter
step even if the raw hit rate looked fine.

Input: a CSV with one row per generated design and at minimum a score column
and an RMSD-to-known-positive column. A boolean "hit" column is strongly
preferred over deriving hits from the RMSD cutoff alone, because a low-RMSD
pose that misses the actual anchor residues/motif is not a real hit (see the
skill's pocket-recapitulation step) — an RMSD cutoff alone can't tell the two
apart.

Usage:
    python score_rmsd_correlation.py designs.csv \
        --score-col score --rmsd-col rmsd_to_positive \
        --hit-col is_near_native_hit --top-k 200

    # No hit column available — fall back to RMSD-cutoff-only (weaker; says
    # so in the output):
    python score_rmsd_correlation.py designs.csv \
        --score-col score --rmsd-col rmsd_to_positive \
        --rmsd-cutoff 3.0 --top-k 200

Requires: pandas, scipy, numpy (pip install pandas scipy numpy).
"""

import argparse
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def parse_args():
    p = argparse.ArgumentParser(
        description="Score-vs-RMSD correlation and top-K enrichment gate "
        "for a generative binder/peptide design benchmark pool."
    )
    p.add_argument("csv", help="Per-design results table (one row per design).")
    p.add_argument(
        "--score-col", default="score", help="Column with the model's own ranking score (default: score)."
    )
    p.add_argument(
        "--rmsd-col",
        default="rmsd",
        help="Column with RMSD to the best-matching known positive (default: rmsd).",
    )
    p.add_argument(
        "--hit-col",
        default=None,
        help="Boolean/0-1 column marking a real near-native hit (RMSD cutoff AND "
        "anchor residues/motif satisfied). Strongly preferred over --rmsd-cutoff.",
    )
    p.add_argument(
        "--rmsd-cutoff",
        type=float,
        default=None,
        help="Fallback: derive hits as rmsd <= cutoff when --hit-col is not available. "
        "Weaker than --hit-col — see the skill's note on pocket recapitulation.",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=200,
        help="Size of the top-K-by-score slice to check for hit enrichment (default: 200).",
    )
    p.add_argument(
        "--higher-is-better",
        action="store_true",
        default=True,
        help="Set if a higher model score means a better/more confident design (default: True).",
    )
    p.add_argument(
        "--lower-is-better",
        dest="higher_is_better",
        action="store_false",
        help="Set if a lower model score means a better/more confident design.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    df = pd.read_csv(args.csv)

    for col in (args.score_col, args.rmsd_col):
        if col not in df.columns:
            sys.exit(f"Column '{col}' not found in {args.csv}. Columns present: {list(df.columns)}")

    df = df.dropna(subset=[args.score_col, args.rmsd_col]).copy()
    n = len(df)
    if n < 10:
        print(f"Warning: only {n} usable rows after dropping NaNs — correlation and "
              "enrichment estimates below will be noisy.", file=sys.stderr)

    # --- hit definition ---
    if args.hit_col:
        if args.hit_col not in df.columns:
            sys.exit(f"--hit-col '{args.hit_col}' not found. Columns present: {list(df.columns)}")
        hit = df[args.hit_col].astype(bool)
        hit_basis = f"'{args.hit_col}' column (RMSD cutoff + anchor residues/motif)"
    elif args.rmsd_cutoff is not None:
        hit = df[args.rmsd_col] <= args.rmsd_cutoff
        hit_basis = (
            f"rmsd <= {args.rmsd_cutoff} only — no anchor/motif check available. "
            "This overstates real hits; add a --hit-col when you can."
        )
    else:
        sys.exit("Provide either --hit-col or --rmsd-cutoff so hits can be defined.")

    n_hits = int(hit.sum())

    # --- Spearman correlation, full pool ---
    rho, pval = spearmanr(df[args.score_col], df[args.rmsd_col])
    # Report correlation in a sign-agnostic "does score track RMSD" framing:
    # if higher score = better and rho is negative, that's the good direction
    # (high score -> low RMSD). Flip sign so "expected_sign_rho" is always
    # positive-good regardless of scoring convention.
    expected_sign_rho = -rho if args.higher_is_better else rho

    # --- top-K enrichment ---
    k = min(args.top_k, n)
    ascending = not args.higher_is_better
    top_k_df = df.sort_values(args.score_col, ascending=ascending).head(k)
    hits_in_top_k = int(hit.loc[top_k_df.index].sum())
    frac_hits_in_top_k = hits_in_top_k / k if k else float("nan")
    frac_hits_overall = n_hits / n if n else float("nan")
    frac_of_all_hits_captured = hits_in_top_k / n_hits if n_hits else float("nan")
    enrichment = (frac_hits_in_top_k / frac_hits_overall) if frac_hits_overall else float("nan")

    print("=" * 72)
    print("Score <-> RMSD gate")
    print("=" * 72)
    print(f"Pool size (usable rows):        {n}")
    print(f"Hit definition:                 {hit_basis}")
    print(f"Hits in full pool:              {n_hits} ({frac_hits_overall:.1%})")
    print()
    print(f"Spearman rho (score, rmsd):     {rho:+.3f}  (p={pval:.2e})")
    print(f"  scoring convention:           {'higher is better' if args.higher_is_better else 'lower is better'}")
    print(f"  'good direction' rho:         {expected_sign_rho:+.3f}  "
          "(positive = score tracks RMSD in the direction you want)")
    print()
    print(f"Top-{k} by score:")
    print(f"  hits inside top-{k}:           {hits_in_top_k} ({frac_hits_in_top_k:.1%} of the slice)")
    print(f"  fraction of all hits captured: {frac_of_all_hits_captured:.1%}")
    print(f"  enrichment vs. random top-{k}:  {enrichment:.2f}x "
          "(1.0x = score is no better than random ordering)")
    print("=" * 72)

    if expected_sign_rho > 0.4 and enrichment > 2:
        verdict = (
            "Score looks like a trustworthy blind filter on this evidence — "
            "reasonable to adopt for triage on new targets without re-deriving "
            "structural confirmation every time. Still plan the wet-lab gate."
        )
    elif expected_sign_rho > 0.15 or enrichment > 1.3:
        verdict = (
            "Weak signal. Score is doing something but is not a strong "
            "substitute for structural filtering — keep a re-ranking or "
            "orthogonal filter step in the pipeline."
        )
    else:
        verdict = (
            "No meaningful signal. Do not rely on the self-score alone for "
            "blind triage on new targets."
        )
    print(f"\nReading: {verdict}")


if __name__ == "__main__":
    main()
