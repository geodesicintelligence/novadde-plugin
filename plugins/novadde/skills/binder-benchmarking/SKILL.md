---
name: binder-benchmarking
description: Benchmark a generative binder/peptide design model (BoltzGen and similar tools on geodesic) against targets with an experimentally validated ligand before trusting it on a real campaign. Use when standing up or re-validating a design pipeline, when hit rate looks target-dependent and it is unclear whether the model is missing the pocket or designing badly inside it, when deciding whether a model's own score can be trusted for triage without full structural re-ranking, or when writing up a benchmarking report for review.
---

# Benchmarking a generative binder/peptide design model

This codifies the review of an internal BoltzGen benchmarking pass (GABARAP / MCL1 / MDM2 against the RFpeptides target set). It is not BoltzGen-specific — the same protocol applies to any generative binder or peptide design model on `geodesic` (rfdiffusion3, proteina, boltzdesign, proteinhunter) before it is trusted on a target with no known answer.

What is here

| path | what it is |
|---|---|
| `SKILL.md` | this protocol |
| `scripts/score_rmsd_correlation.py` | the score-vs-RMSD gate (Spearman correlation + top-K enrichment) from the section below — run it on a per-design CSV instead of re-deriving the calculation each time |

## Why this exists

A design model that "runs" is not the same as a design model that is *any good on the target you actually care about*. The only cheap check before spending compute or foundry budget on a blind target is recapitulation: pick targets where a real binder's structure is already known, and see whether the model's own outputs, scored and filtered the way you would filter them blind, land close to that known answer. This skill is the checklist for doing that, reading the result, and deciding what it licenses you to do next — it stops short of telling you the model is *right*, only what a given result does and doesn't prove.

## The protocol

1. **Pick targets with an experimentally validated ligand you can hold out**, ideally reusing a published benchmark set (e.g. the RFpeptides paper's targets) so your numbers are comparable to a known baseline. Prefer a spread of pocket types — a well-defined groove, a deep or occluded pocket, a PPI interface — since generation quality is not uniform across them.
2. **Generate a real-sized pool per target**, not a handful of samples. The worked example below ran 4,232–10,000 designs per target; small pools make the hit-rate percentage meaningless.
3. **Score every design against the known positive** with:
   - RMSD to the best-matching known active ligand (name which known structure/ligand it was matched against — don't just report a bare number).
   - Hit rate: fraction of the pool at or below a fixed RMSD cutoff (3 Å is a reasonable default for peptide/miniprotein binders; state whatever cutoff you use).
   - Pocket recapitulation: whether the *known* pocket is engaged at all, and specifically whether the known anchor residues / binding motif are hit (e.g. two key hydrophobic anchors, or a defined sequence motif like an `LxxxGD` groove signature) — a design can sit in the right pocket by RMSD and still miss the actual determinant of binding.
4. **Report per target, not just in aggregate.** A single blended hit rate hides exactly the target-dependence this benchmark exists to find.

## Picking a proxy target when your real target has none

Step 1 above assumes you can hold out *a* target with a known answer — it does not require that target to be the one you actually care about. This benchmark exists to build trust in the model/pipeline that you then spend on a real target, so there are two distinct situations:

- **Your real target has its own known positive** (a co-crystal structure, a published validated binder — it doesn't have to be something you designed yourself). Run the protocol on the real target directly. This is the strongest case: the benchmark result transfers with no extra assumption.
- **Your real target is genuinely blind** — no known binder to hold out at all. Then pick one or more proxy targets that are already characterized (reuse a published set, e.g. RFpeptides', as in the worked example) and, as best you can tell, resemble your real target's binding-site geometry — same broad pocket class: a defined groove, a deep/occluded pocket, a PPI interface. Running the protocol on the proxy tells you how the model behaves on *that class of site*, not on your specific target.

In the blind case, say so explicitly in the write-up: a clean recapitulation result on a deep-pocket proxy licenses cautious optimism that the model is competent on deep pockets in general, not a claim that it has found anything real on your actual target. That gap is exactly why the wet-lab gate below still applies — arguably more so, since there is no in-silico recapitulation possible on the real target itself until you have a candidate structure to check against.

## Diagnosing a low hit rate: the hotspot ablation

A low hit rate has (at least) two different causes that look identical in the summary table but need opposite fixes:

- **Localization failure** — the model is searching the wrong part of the target (wrong sub-pocket, wrong face of a PPI interface).
- **Generation-quality failure** — the model finds the right pocket but can't design well inside it (can't satisfy the geometry, misses the key motif, etc.).

You cannot tell these apart from an unconstrained run alone. The disambiguating experiment is a **hotspot ablation**: rerun the same target with the pocket/anchor residues specified as a hotspot, holding everything else constant, and compare hit rate and pocket recapitulation against the unconstrained run.

- If specifying the hotspot fixes it → the earlier run's problem was localization, not the model's design quality. Note this for the target and move on; it does not indict the model in general.
- If specifying the hotspot does *not* fix it → the model has a real generation-quality ceiling on that target/pocket type, and no amount of pointing it at the right place will paper over that.

Only after running this ablation should you generalize a rule like "give hotspots for deep-pocket or PPI targets" — state it as a target-class recommendation backed by the ablation result, not as a default applied everywhere. A shallow, well-characterized groove may not need one at all (see the MDM2 row below, which hit well with no hotspot).

## Gate: does the model's own score track RMSD?

Once you have a pool with known RMSD-to-positive for every design, you can check whether the model's *own* ranking score is usable for blind triage, where you will never have an RMSD to check against:

1. Restrict to the near-native subset: designs at or below your RMSD cutoff **and** hitting the known anchor residues/motif (RMSD alone is not enough — a low-RMSD pose that misses the actual binding determinant is not a real hit).
2. Check where that subset falls in the model's own score ranking over the *full* pool — e.g. what fraction of it lands in the top 200 by score (enrichment), and/or the rank correlation (Spearman) between model score and RMSD-to-positive across the full pool.
3. Read the result as a gate, not a pass/fail on the model:
   - **High correlation / strong enrichment** → the model's self-score is a trustworthy blind filter; the pipeline can be adopted for triage on new targets without re-deriving structural confirmation every time.
   - **Weak or absent correlation** → do not rely on the self-score alone downstream; keep a structural re-ranking or orthogonal filter step in the pipeline even after this benchmark looks fine on hit rate.

`scripts/score_rmsd_correlation.py` runs this check on a CSV of per-design results (score, RMSD-to-positive, and ideally a boolean near-native-hit column) and prints the Spearman rho and top-K enrichment described above, plus a plain-language reading of the result:

```
python ${CLAUDE_SKILL_DIR}/scripts/score_rmsd_correlation.py designs.csv \
    --score-col score --rmsd-col rmsd_to_positive \
    --hit-col is_near_native_hit --top-k 200
```

Requires `pandas`, `scipy`, `numpy`. Run `--help` for the full flag list, including the `--rmsd-cutoff` fallback for when you don't yet have a proper hit column (weaker — see the script's own warning about why).

## What this benchmark does and doesn't prove

Be explicit about this distinction when writing up results — it's easy to overclaim:

- This is a **binding-mode recapitulation** test: new molecules the model designed, scored against a structure someone else already solved and validated (e.g. by SPR). It shows the model *can rediscover a known answer*.
- It is **not** a self-consistency benchmark (a design scored against a structure predicted for that same design — e.g. RFpeptides' own reported 0.4–1.7 Å is design-vs-self-folded-structure). Don't quote self-consistency numbers and recapitulation numbers as if they measure the same thing.
- It is **not** experimental validation. Nothing in this protocol tests whether a *novel* design — one with no known positive to recapitulate — actually binds. A clean recapitulation result licenses moving to the next gate below; it does not license claiming the model's novel outputs are validated binders.

## Escalation: the wet-lab gate

A strong in-silico result (good hit rate, good pocket recapitulation, high score–RMSD correlation) is a necessary condition for adopting a pipeline, not a sufficient one. Before relying on it for a real campaign's worth of decisions, plan to send a batch of the pipeline's top-scoring *novel* candidates (not the recapitulation designs) for an actual binding assay (SPR/BLI via an external foundry — see `protein-binder-campaign` for the in-silico-only boundary and why wet-lab work is necessarily an external, billed step). Treat the in-silico gate as what earns the budget for that wet-lab batch, not as a replacement for it.

## Worked example: BoltzGen vs. GABARAP / MCL1 / MDM2

From the review pass this skill is drawn from. Cutoff = 3 Å.

| Target | Hotspot given | Pool size | Best RMSD to known positive | ≤3 Å fraction | Pocket recapitulation |
|---|---|---|---|---|---|
| GABARAP | yes | 4,232 | 0.73 Å (GAB_D8); 0.58 Å (GAB_D23) | 2,884/4,232 (68%) | Hit — 96% of top 200 satisfy both Trp5/Ile8 anchors; run stopped early on strength of result |
| MCL1 | no | 7,672 (in progress) | 1.67 Å (MCB_D2) | 30/7,672 (0.4%) | Partial — reaches the BH3 groove, but no design carries the canonical `LxxxGD` motif |
| MDM2 | no | 10,000 | 0.32 Å (p53 peptide, PDB 4HFZ) | 1,325/10,000 (13%) | Hit — 483 designs satisfy the p53 F-x3-W-x2-L anchor triad |

Reading this table is exactly where the two techniques above apply: MCL1's low hit rate is ambiguous between localization and generation-quality failure until the hotspot-ablation rerun comes back, and no adoption decision should be made off this table alone until the score–RMSD correlation is computed and a wet-lab batch is planned for the pipeline's actual novel candidates.

## See also

- `geodesic` — how to submit/poll/read a `boltzgen` (or other binder-model) job that produces the pool this benchmark scores.
- `protein-binder-campaign` — the full campaign structure this benchmark is a pre-flight check for, including why wet-lab assay is necessarily an external step.
