---
name: plm-variant-scoring
description: Use when scoring or ranking protein variants with a language model likelihood — which convention to use (masked-marginal, wt-marginal, mutant-marginal, pseudo-log-likelihood), what each costs, which direction the sign runs, why a multi-mutant needs a different forward pass than a point mutant, and why a summed likelihood cannot be compared across lengths. `fair-esm2` owns running the model; this owns what the number means. Triggers include "score these mutations with ESM", "masked marginal or wt marginal", "rank these designs by likelihood", "can I score an indel", "which ESM checkpoint for variant effects", "why is my ESM score negative".
---

# Scoring variants with a language model

`fair-esm2` runs the model. This says which number to compute and what it can be compared with.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/score_variants.py \
    --logprobs lp.npz --convention masked-marginal --variants A24G

python3 ${CLAUDE_SKILL_DIR}/scripts/score_variants.py --selftest
```

The script takes **log-probabilities**, not logits, and requires `--convention` — for the reason
in the next section.

## Two conventions take the same matrix and are different numbers

| convention | the matrix is | cost |
|---|---|---|
| **wt-marginal** | one forward pass over the wild-type, nothing masked | 1 pass, whole DMS |
| **masked-marginal** | L passes; row *i* from the pass masking position *i* | L passes per sequence |

Both are `(L, 20)` float arrays. **Nothing about the file says which one it is.** So the script
will not infer it: you declare it, and it is stamped into the output beside the score. A number
computed one way cannot then be silently compared with one computed the other way.

All four conventions in Meier *et al.* (NeurIPS 2021, Appendix A — the formulas are in the
supplement, not the main text):

```
masked-marginal (a)  Σ_{i∈M} log p(x_i=x_i^mt | x_−M) − log p(x_i=x_i^wt | x_−M)
mutant-marginal      Σ_{i∈M} log p(x_i=x_i^mt | x^mt) − log p(x_i=x_i^wt | x^mt)
wt-marginal          Σ_{i∈M} log p(x_i=x_i^mt | x^wt) − log p(x_i=x_i^wt | x^wt)
pseudo-likelihood    Σ_{all i} log p(x_i=x_i^mt | x_−i^mt) − log p(x_i=x_i^wt | x_−i^wt)
```

`x_−M` is masked at **every** mutated position at once. Note the last sum runs over *all*
positions, not just the mutated ones.

**The recommendation is real but thin.** Table 5, mean |Spearman ρ| over 10 validation assays:
masked 0.582, mutant 0.578, wt **0.572**, pseudo-likelihood 0.552. Masked-marginal wins by
**0.004** over mutant-marginal and 0.010 over wt-marginal, with no significance test and n=10. The
paper says so itself: wt-marginals give "a minor 1% decrease in absolute performance, while
requiring very limited computational resources." If L forward passes per sequence is inconvenient,
wt-marginal costs you about one Spearman point.

**`mutant-marginal` is not in the released code.** `predict.py` offers `wt-marginals`,
`masked-marginals` and `pseudo-ppl` only. Four conventions in the paper, three in the repository.

## A multi-mutant is not a sum of point mutants you already have

This is the one that silently produces a wrong number.

For a **single** substitution, a per-position masked table *is* Strategy (a). For a **multi-mutant**
it is not: (a) masks every mutated position in **one** pass, which needs a forward pass per variant
set. Reusing the per-position table gives Strategy (b)/(c) instead — and on the paper's own PABP
doubles set that is |Spearman ρ| **0.482 / 0.483** against **0.692** for (a). A 0.21 gap.

The reference implementation walks into it: it masks one position at a time, and its `label_row`
parses a single `A123B` token and never splits a multi-mutant at all. The script here refuses
rather than reusing the table, and says what the reuse would cost.

Accuracy also falls steeply with depth regardless of convention. ProteinGym, 217 substitution
assays, ESM-2 650M: **0.422** at depth 1, **0.248** at depth 2, 0.205 at depth 3, 0.163 at depth 4.
Roughly halved by the second mutation.

The additive model itself is asserted from the training objective, not tested against a
non-additive alternative.

## The sign is inferred, and the benchmark cannot check it

Score = `log p(mutant) − log p(wild-type)`. **Higher means the model finds the mutant more likely.**
Every formula puts the mutant term first and the reference implements
`token_probs[..., mt] - token_probs[..., wt]`.

But the paper never asserts the direction in prose, and — this is the part that matters — **every
result it reports is |Spearman ρ|, an absolute value**, because DMS assays disagree about the sign
of what they measure. So **a flipped sign reproduces the paper's numbers exactly**. A correlation
against a benchmark cannot catch it.

Check the direction against a substitution whose answer you already know, not against a
correlation. The script's `--selftest` does exactly that.

## A summed likelihood is not comparable across lengths

Pseudo-log-likelihood is a **sum** over positions (Salazar *et al.*, ACL 2020, which Meier cites
for it). Every term is a log probability and therefore negative, so the sum is extensive: it grows
more negative with length.

The script reports `pll_summed` and `pll_per_residue` and says only the second can be compared
across lengths. They genuinely disagree — a 5-residue sequence at −1.00 per residue sums to −5.0
and outranks a 50-residue sequence at −0.90 per residue summing to −45.0, while per-residue ranks
them the other way. `--selftest` asserts that disagreement on a constructed pair.

Meier *et al.* never address this: all 41 of its benchmarks hold the wild-type fixed, so length is
constant and the question cannot arise. The length argument is arithmetic, not a citation.

Point mutations are unaffected — a log-odds ratio at a fixed position is intensive, and the two
sequences have the same length.

## Indels: change model class, do not patch the formula

The paper says **nothing**. "insertion", "deletion" and "indel" appear zero times in the main text
and zero times in the supplement.

Structurally the masked-, wt- and mutant-marginal scores are all defined as a log-odds ratio *at a
position shared by both sequences*. An insertion or deletion means there is no such position and
every downstream index shifts, so the difference is **undefined**, not merely inaccurate.
Pseudo-likelihood can be computed — it scores whole sequences — but then you are comparing summed
PLLs across different lengths, which is the previous section.

ProteinGym keeps a separate indel benchmark (74 assays). Its leaderboard has 24 entries and **not
one is a masked language model** — every one is autoregressive (PoET, Progen2, RITA, Tranception,
ProtGPT2), an HMM, or a classical predictor. The field's answer to indels is a different model
class.

## Which checkpoint

ProteinGym, 217 substitution assays, average Spearman (bootstrap SE ≈ 0.012):

| model | ρ |
|---|---|
| ESM-2 650M | **0.414** |
| ESM-1v, ensemble of 5 | 0.407 |
| ESM-2 3B | 0.406 |
| ESM-2 15B | 0.400 |
| ESM-1v, single seed | 0.374 |

- **ESM-2 650M and the ESM-1v ensemble are indistinguishable** (0.007 apart, SE 0.012). Using ESM-2
  for variant effects is defensible.
- **ESM-2 does not improve with scale on this task — it degrades.** 650M > 3B > 15B. Do not reach
  for the 15B checkpoint for variant scoring.
- One ESM-2 650M merely *matches* five ensembled ESM-1v models, and clearly beats a single one.
- Neither is state of the art on that leaderboard; MSA- and retrieval-based methods lead it.

Ensembling ESM-1v's five seeds is worth **+0.025** (paper Table 2) to **+0.033** (ProteinGym) —
several times the masked-vs-wt margin, for 5× the compute. **How the five are combined is never
stated**, and the repository ships no combination step; mean-of-log-odds is the usual assumption,
not a documented method.

The ESM-2 paper did not systematically evaluate variant effects. An author's position is that the
protocol is unchanged from ESM-1v and that preliminary experiments matched its performance.

## On antibodies, the number is worst exactly where you need it

Olsen, Moal & Deane, *Bioinformatics* 40(11), 2024 — masked-residue perplexity, random ≈ 20:

| model | heavy, whole | framework | CDR1/2 | **CDR-H3** | light CDR-L3 |
|---|---|---|---|---|---|
| ESM-2 | 2.83 | 2.04 | 4.98 | **10.97** | 10.92 |
| AbLang-1 | 1.33 | 1.11 | 1.40 | **3.68** | 1.79 |

ESM-2's CDR-H3 perplexity is ~4× its whole-chain value and roughly halfway to random. Their
sentence is the one to remember:

> "As the CDRs only make up a small proportion of the residues in a chain the poor performance for
> this region is masked in the results for the whole chain."

A whole-chain likelihood therefore looks fine while being uninformative in the only region that
determines binding. Framework residues are evolutionarily constrained; hypervariable loops are not.

Do not overstate it either: ProteinGym's binding category is the weakest for both models but not
catastrophic (ESM-2 650M 0.337 binding vs 0.425 activity), and general PLMs have guided real
affinity-maturation campaigns. The defensible statement is that **general-PLM likelihoods are far
less reliable in CDRs than in framework, and whole-chain metrics conceal it** — not that they are
useless on antibodies.

`antibody-interface-metrics` already rules that a likelihood is a naturalness regulariser and not a
binding term. This is why.

## What is not established

- **Length normalisation for cross-length ranking.** The paper does not address it; the argument
  here is arithmetic.
- **How the ESM-1v ensemble is combined.** Not stated anywhere.
- **The ESM-2 paper's own text** on variant effects could not be retrieved (paywalled); the claim
  above rests on ProteinGym and an author's public statement.
- **Three defects in the source, transcribed rather than corrected:** the prose label for Strategy
  (b) does not match its printed formula; Appendix A says masked-marginal (a) "performs best" on
  the doubles set while its own Table 7 shows mutant-marginal fractionally higher (0.694 vs 0.692);
  and Table 7's caption names the wrong dataset.
