---
name: ipsae-calculate
description: Use when ipSAE or interface PAE has to be computed from a PAE matrix and a structure, rather than read off whatever a folding model already printed. Takes any PAE matrix plus the matching mmCIF/PDB, including this deployment's own predictors. This is the executable half of `antibody-interface-metrics`, which owns what the numbers mean. It scores each chain pair separately and will not hand back one number for a multi-chain complex until you say which chains are binder and which are target. Triggers include "compute the ipSAE", "score this NovaAtom output", "what is the ipSAE of my binder against the antigen", "which interface did that number come from", "my binder is a VH/VL pair", "get me the interface PAE".
---

# Computing ipSAE

`antibody-interface-metrics` owns what these numbers mean — why ipSAE reads lower than ipTM,
what to gate on, how to weigh a composite. This is the compute half. It owns the arithmetic
and the bookkeeping around it, and it is the tool that section's invariants are addressed to.

```bash
# A binder against a target. This is the form you almost always want.
python3 ${CLAUDE_SKILL_DIR}/scripts/ipsae.py \
    --pae pae.json --structure model.cif --binder-chains H,L --target-chains G

# Every chain pair, no headline number. Use when you do not yet know the roles.
python3 ${CLAUDE_SKILL_DIR}/scripts/ipsae.py --pae pae.json --structure model.cif

python3 ${CLAUDE_SKILL_DIR}/scripts/ipsae.py --selftest   # 50 known answers, before you trust it
```

NumPy is the only dependency. No network, no GPU, no folding — it scores a prediction someone
else already made. `--selftest` is the fastest way to find out whether NumPy is actually there.

## Say which chains are the binder

This is the whole reason the skill exists. ipSAE is defined per ordered chain pair, so a tool
that reduces a complex to one number has to pick a pair — and a maximum over all of them picks
the best-predicted interface, which for a paired VH/VL binder is **VH–VL**, not the paratope.
It is conserved, well packed, and predicted far better than anything you designed.

On the fixture in `--selftest`, the three pairs score H–L **0.2835**, H–G **0.0421**, L–G **0**.
A blind maximum returns 0.2835 — 6.7x the number anyone wanted, and about a different interface.

So: with `--binder-chains` and `--target-chains`, only pairs crossing that boundary are scored
and `best_cross_interface` is the best of them. Without them, every pair is reported,
`best_cross_interface` is `null`, and `headline_note` says why. The script never invents the
headline number, and it refuses a chain named on both sides.

## What comes back

One object per chain pair. `ipsae` is the max of the two directions; `directional` holds both,
**keyed by chain name** — `"H->G"`, not `a_to_b`, because the chain order flips between a scoped
and an unscoped run of the same data and a positional label would silently swap meaning.
`winning_direction` names a key in that object. `anchor_residue` is the residue the maximum came
from, with the `n0res` and `d0` that produced it, so a score traces back to one row of the matrix.

`interface_pae` is separate and is **not** part of ipSAE. Contacts are residue pairs whose
closest heavy atoms are within `--contact-distance` (5 Å), counted once per residue pair, never
filtered by `--pae-cutoff` — filtering an average by the thing being averaged flatters it.

`status` distinguishes the zeros, because they are not one fact:

| `status` | what happened | what to do |
|---|---|---|
| `ok` | scored | read it |
| `no_qualifying_pairs` | chains touch, no residue pair cleared the cutoff | a confidence failure |
| `no_contacts` | the chains never come within the contact distance | a docking failure |

A crash is none of these: it exits **2**, prints one line to stderr, and writes nothing to stdout.
Nothing here returns `0.0` for a failed measurement.

## Where the PAE comes from, and why it is probably not a geodesic job

**Measured on this deployment, 2026-09-15, across every job it holds: not one artifact is a PAE
matrix.** Nine jobs, five of them completed BoltzGen runs with 14-16 artifacts each. No `.npz`, no
file with `pae` in its name, in any of them.

What a completed BoltzGen job actually returns:

```
design.yaml · logs/*.log · all_designs_metrics.csv
rank01..rank10 *.cif · final_designs_metrics_10.csv · results_overview.pdf
```

and `pae` appears only as a **scalar** in per-design metrics —
`"iptm":0.379, "ptm":0.777, "pae":9.676`. That is one number, a mean. **A matrix cannot be
recovered from it, so ipSAE is not computable from a BoltzGen job here.**

`esmfold` is **unknown**, not cleared: every job of its on this deployment failed before producing
output, so there is no completed run to inspect. `protenix` has since been **cleared negative**: a
run in its default `msa` mode completed on 2026-09-15 and returned summary JSON with no PAE matrix
among its artifacts — one run, in one mode, which narrows the question rather than closing it. `describe_model` does not
settle it either -- the protenix spec mentions `pae` zero times, and `novaatom`'s confidence keys
are `confidence`, `plddt`, `iplddt`, `ptm`, `iptm`, `ipde`, all scalars -- but a spec lists summary
columns, not an artifact inventory. Absence there is not evidence of absence in the output.

So: **read the finished job's artifact list.** If it holds a square PAE, this script takes it; if
it holds only scalars, ipSAE is unavailable for that run and that is the answer.

```bash
# any square PAE plus its matching structure, from wherever you actually have one
python3 ${CLAUDE_SKILL_DIR}/scripts/ipsae.py \
    --pae pae.npz --structure model.cif --binder-chains H,L --target-chains G
```

Two ways this comes up empty, and they are not the same:

- **A confidence summary is not a PAE.** `iptm`, `ptm`, `gpde`, `ipde` and a scalar `pae` are
  summaries. Reporting one of them in place of ipSAE is the substitution this whole skill exists
  to prevent.
- **The run has no PAE head, or the deployment does not persist one.** Say so. There is no ipSAE
  for that run, and a number obtained another way is not one.

## Cutoffs are a choice, and they travel with the number

`--pae-cutoff` defaults to 10 Å, which is what the reference program's own usage examples use;
the paper says 10 or 15 "may be most suitable" and neither is canonical. It is **not** monotone —
lowering it drops high-error pairs but also shrinks `n0res`, which shrinks `d0` — so you cannot
reason "stricter cutoff, lower score", and you must not pick the one that flatters a design. Fix
one across everything you compare. Both cutoffs are echoed in the output so a number cannot get
separated from the settings that produced it.

`--contact-distance` is iPAE's, not ipSAE's, and is independent of `--pae-cutoff`. It is a
minimum-heavy-atom distance; the reference program's `dist_cutoff` is a CB–CB distance feeding
auxiliary counters. Different quantity, same-sounding name.

## What it deliberately does not do

**It does not zero a score for chains that are far apart.** ipSAE has no distance term: in the
reference implementation the distance cutoff reaches only the `dist1`/`dist2` counters, never the
score, so two chains 50 Å apart with confidently low inter-chain PAE still score. If you need
"are they even touching", read `min_interchain_distance` and the `no_contacts` status — that is
what they are for. (pDockQ *does* zero on distance. That is a different metric.)

**It does not compute `ipSAE_d0chn` or `ipSAE_d0dom`,** and neither is standard ipSAE. It does not
handle nucleic acids, and it does not reproduce the author's PyMOL output or full contact tables —
for those, run the reference program itself.

**It does not guess a residue mapping.** The PAE must be square and match the structure's protein
residues 1:1 in order; a mismatch stops the run and says by how much. Residues are those with a CA,
so ligands and waters drop out, hydrogens are excluded from contact distances, and chain labels
come from the `auth_*` columns — the ids you see in PyMOL.

## Verify before you trust it

`--selftest` builds a three-chain fixture as both PDB and mmCIF and makes 50 checks over it,
including the four invariants above and the exact text of every refusal. Three independent
confirmations that the arithmetic is right:

- `d0` is **bit-identical** to the reference implementation's `calc_d0_array` — the function behind
  its headline ipSAE column — for every length 1–60. **At exactly n0res=27 this script returns
  1.0389, not 1.0**: `d0 = 1.0` holds *below* 27, and 27 itself evaluates the formula. The
  reference's scalar `calc_d0` returns 1.0 there instead, and that one feeds only the
  `d0chn`/`d0dom` columns, which are not standard ipSAE. Upstream deliberately moved
  to this convention on 2026-01-03 ("now returns 1.00 instead of 1.04 for minimum value"), so an
  implementation still clamping the length up to 27 is following a superseded version.
- Cross-checked against a separate independent implementation on the same input: all six directed
  scores agree to **4.9e-07**, as do anchor residue, `n0res`, `d0`, contact counts and iPAE.
- Verified by mutation: 16 deliberate defects, each one turning the selftest red.

`test_skill.py` beside it checks this document against the script: that every number quoted here
is the number the script prints, that every flag named here still exists, that no invocation has
gone relative again, and that the frontmatter still survives the loader that can drop a skill on a
log line nobody reads. It is mutation-tested the same way — 11 documentation defects, each turning
it red.
