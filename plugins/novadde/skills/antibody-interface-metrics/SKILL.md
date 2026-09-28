---
name: antibody-interface-metrics
description: Use when reading or ranking the numbers a co-folding model returns for an antibody-antigen complex — ipTM, ipSAE, pLDDT, PAE, a ranking score, an ESM-2 likelihood, a contact fraction — or when setting a gate on them. Covers why ipTM flatters a small paratope, what ipSAE changes, which distance cutoff belongs to which job, the CDR-versus-framework contact criterion, how to weight a composite objective, and which developability liabilities are computable rather than narratable. Triggers include "is this ipTM good", "why is ipSAE lower than ipTM", "what threshold should I gate on", "rank these designs", "which metric means it binds", "is a high likelihood better".
---

# Reading the interface metrics on an antibody design

**The one invariant worth memorizing:**

> Every number a co-folding model returns is a **confidence**, not an affinity — and the one most
> often read as affinity, ipTM, is most permissive exactly where antibodies live: a small paratope
> on a large antigen.

A VHH that grips the antigen with its framework can score better than one that grips it with CDR3.
Nothing in the confidence panel objects. The panel tells you how sure the model is about a
structure; whether that structure is an antibody doing an antibody's job is a separate question you
have to ask with a separate number.

## What each number is, and what it is not

Hand this table to a model alongside the numbers. A bare metric name invites the wrong reading; the
caveat is the load-bearing half.

| Metric | Means | Does **not** mean |
|---|---|---|
| `ipTM` | interface confidence, 0–1 | measured affinity; and see below on small interfaces |
| `ipSAE` | interface confidence from aligned error, computed per residue | affinity; comparable to ipTM on the same scale |
| `pTM` | global fold confidence, 0–1 | anything about the interface |
| `pLDDT` | per-residue local confidence, 0–100 (or 0–1 normalized) | that the pose is right — a confident loop can be confidently misplaced |
| `i_pLDDT` | pLDDT restricted to interface residues | a contact count |
| `PAE` / `i_PAE` | expected positional error between two residues, Å | a distance |
| `ranking_score` | the backend's own composite | independent evidence — it **overlaps** the metrics above, so do not count it twice |
| ESM-2 pseudo-log-likelihood | sequence plausibility under a language model | binding. A more "natural" sequence is not a better binder |
| `cdr_contact_fraction` | CDR share of the binder's interface residues | affinity; interpret with the hotspot evidence |
| `framework_contact_fraction` | framework share of the same | — lower is preferred, see the paratope criterion |
| RMSD to a pre-refold pose | pose consistency | affinity |

Two rules that fall out of the table and are worth stating separately to any agent doing the
ranking: **the search objective is not the final order** — it cannot see developability, pose
consistency, or recurring failure modes — and **a likelihood is only comparable between sequences
of comparable length**.

## Why ipTM flatters a nanobody

ipTM is a TM-score-shaped quantity. Its length scale `d0` comes from the **total** length of the
chain pair:

```
d0 = 1.24 * (L - 15)^(1/3) - 1.8        # L is the pair's TOTAL length, so this floor
                                        # never binds here; see ipSAE below, where it does
```

and the score averages over every cross-chain residue pair. For the 125-residue VHH and
209-residue antigen of a real quickstart config that is 26,125 pairs, of which a few hundred are
a real interface. A large `L`
makes `d0` large, which makes the per-pair term forgiving, and the few hundred pairs that matter are
diluted by the ~25,000 that do not. A correct epitope contact and a plausible mis-dock land close
together.

This is not a flaw in ipTM; it is ipTM answering the question it was built for — whole-complex
agreement — on a problem where the interesting part is 1–2% of the pairs.

## What ipSAE changes

ipSAE (Dunbrack lab) keeps the TM-score form and fixes the normalisation:

- only residue pairs whose **PAE clears a cutoff** enter the score — 10 Å and 15 Å are both in
  common use and neither is canonical, so fix one for a comparison and report which;
- `d0` is computed **per residue** from `n0res` — how many partners that residue actually has under
  the cutoff — instead of from summed chain length;
- **no distance term at all.** Two chains 50 Å apart with confidently low inter-chain PAE still
  score. In the reference implementation the distance cutoff reaches only the reported `dist1` and
  `dist2` residue counters, never any ipSAE variant, and the only zeroing is "no residue pair
  cleared the PAE cutoff". (pDockQ *does* go to zero on distance. That is a different metric, and
  conflating the two is where the belief comes from.) So check contact separately — a score cannot
  tell you the chains touch.

The consequence: ipSAE measures **how good the interface is, given that there is one.** It will read
*lower* than ipTM on the same complex and that is the point — do not treat the gap as a bug or the
two as interchangeable. Report both, rank on ipSAE, and keep ipTM as a shadow metric.

**Know what the numbers actually do at antibody scale.** With `d0 = 1.24(L-15)^(1/3) - 1.8`, a
125-residue VHH against a 209-residue antigen gives ipTM a single `d0` of **6.67 Å**, while a
per-residue `d0` built from ~12 confident partners is **1.00 Å**. The same 5 Å of expected error
therefore scores 0.640 under ipTM and 0.038 under ipSAE — a **17x** gap, from the length scale alone.

And one thing only visible in the implementation: below 27 partners `d0` is **1.00 Å flat**. An
interface residue typically has 5–20 partners under the PAE cutoff, all below that boundary, so **at
antibody scale ipSAE's "per-residue" d0 is effectively pinned at 1.00 Å.** It behaves less like a
smoothly adaptive score and more like a strict PAE threshold: it asks whether a few pairs are
predicted *very* confidently, not how good the interface is on average. Read it that way.

These numbers used to read 1.04 Å / 0.041 / 15x, from clamping the *length* up to 27 rather than
flooring the *output* at 1.0. The reference implementation did exactly that until 2026-01-03, when
it changed deliberately — `# fixed 01.03.2026: now returns 1.00 instead of 1.04 for minimum value`.
An implementation still clamping the length scores every small interface about 6% high, uniformly,
so it changes no ranking but makes the numbers incomparable with anyone else's. `ipsae-calculate`
follows the current convention and is bit-identical to the reference's `calc_d0_array` for every
length 1–60.

**The cutoff does not move the score in one direction.** Lowering it drops high-error pairs, which
lifts the surviving mean — but it also shrinks `n0res`, which shrinks `d0`, which pushes the score
back down. Raising it does the reverse on both. So you cannot reason "stricter cutoff, lower score",
and you must not pick the cutoff that flatters a model: fix it across everything you are comparing.
The winning residue and even the winning direction can change with it.

**A multi-chain score is one interface's score, and not necessarily the one you asked about.** ipSAE
is defined per ordered chain pair. An implementation that reduces a complex to a single number by
maxing over every pair will, for a paired VH/VL binder against an antigen, happily return the
**VH–VL** interface — conserved, well packed, and predicted far better than any designed paratope.
On a synthetic VH(120)+VL(110)+antigen(250) case the three pairs scored H–L 0.855, H–G 0.161,
L–G 0.048: the max is 5.3x the number anyone wanted. Always read ipSAE per chain pair, and if a tool
hands you one scalar for a three-chain complex, find out which pair it came from before using it.

## If you are computing ipSAE, not just reading it

These are the invariants of the calculation. Each one names a simplification that looks helpful and
silently produces a different number, so state them to anything doing the arithmetic.

- **PAE is not symmetric.** Row `i` is the aligned residue, column `j` the one being scored.
  Do not average the matrix with its transpose first, and do not take the two directions' minimum
  and call the result ipSAE.
- **The partner set is per row.** For aligned residue `i`, keep the other chain's residues with
  `PAE[i,j] < cutoff` — strictly less than. `n0res` is the size of *that row's* set. It is not the
  sum of the chain lengths, and it is not the union of everything at the interface.
- **`d0` is computed from `n0res`, per row.** `d0 = 1.0` when `n0res < 27`, else
  `1.24·(n0res−15)^(1/3) − 1.8`. Clamping the length up to 27 instead scores every small interface
  about 6% high — uniformly, so it changes no ranking, but it makes the numbers incomparable with
  anyone else's.
- **Average, then maximise, in that order.** Mean `1/(1+(PAE[i,j]/d0)²)` over the qualifying `j`,
  then take the maximum over `i` within the aligned chain. A row with no qualifying `j` scores 0.
- **Raw PAE goes in.** This does not reconstruct AlphaFold's native ipTM, which comes from the
  error distribution rather than the point estimate. Report them as different quantities.
- **A distance cutoff is not part of the standard score.** It belongs to contact statistics and to
  the zero-if-not-touching guard, not to the per-residue sum.
- **Zero has three causes and they are not the same fact.** No pair cleared the cutoff; the chains
  are not in contact; the calculation failed. Only the first two are results. If your pipeline
  returns `0.0` for a crash as well, a failed measurement is indistinguishable from a design that
  does not bind — and the model reading "higher is better" will score it as the latter. Carry a
  status alongside the number and let "unavailable" be a value.

## Three contact criteria, three jobs

"Contact" is not one definition. Using the wrong one silently changes what you are measuring.

| Cutoff | Definition | Use it for |
|---|---|---|
| **~5 Å** | any heavy atom of A within 5 Å of any heavy atom of B | a hard structural gate; the physical contact definition |
| **~8 Å** | Cβ-style contact probability | a soft term inside a differentiable or ranking objective — the AF2-design convention |
| **~20 Å** | generous inter-chain neighbourhood | choosing which residue pairs count as "interface" when averaging a confidence |

Pick per job and **write the cutoff into the result**, not just into a doc. Two scores computed
under different cutoffs are not comparable, and six months later nothing on disk will say which was
used.

## The paratope criterion

This is the number the confidence panel cannot give you: **is the antibody binding the way an
antibody binds?**

Two checks, both computed from the predicted complex at the ~5 Å heavy-atom definition:

- **CDR contact fraction** — unique CDR residues in the binder's interface ÷ unique binder interface
  residues. A majority (> 0.5) is a defensible floor. Counting *unique residues*, not atom contacts,
  matters: one long arginine making forty atom contacts must not outvote six residues making one
  each.
- **CDR3 must touch the epitope at all** — at least one contact between CDR3 and a configured
  hotspot. CDR-H3 dominates the paratope; a design where it contributes nothing is not the molecule
  you asked for, whatever its ipTM.

The useful move is to encode this at **more than one strength**:

1. as a **hard gate** — below the fraction, the candidate is rejected regardless of score;
2. as a **soft term** in the objective — reward CDR contact, penalise framework contact, so the
   search *steers* rather than only being fenced;
3. as a **tiebreak** applied to the rejects — when nothing passes the gate, prefer the candidate
   closest to having a paratope over the one with the best confidence. Otherwise a campaign spends
   its remaining budget polishing the best framework-binder it has.

One asymmetry is worth copying: the positive CDR term may be narrowed to the configured epitope,
while the framework penalty should span the **whole** antigen. *CDRs must touch the epitope; the
framework should touch nothing, anywhere.*

## Weighting a composite objective

If you combine terms into one number:

- **Weight interface terms above global ones.** Interface pLDDT and interface pTM carry the signal;
  global PAE is largely about whether the monomer folded, which for a real framework it did.
- **Keep a sequence-likelihood term small** — a naturalness regulariser, not a driver. The standard
  form is `loss − scale · log-likelihood` with the likelihood non-positive, so it penalises
  implausible sequences without steering toward germline consensus.
- **Do not normalise the weights to sum to 1** unless you mean to. They are coefficients; silently
  rescaling everything because someone added a term is how two campaigns become incomparable.
- **Raise on a missing component; never backfill it** from a different source — least of all from
  the backend's own ranking score. A candidate scored with a substituted term is not comparable to
  one scored without.
- **Stamp the recipe into every result**: a formula version plus the cutoffs actually used.

### A term's dynamic range, not its weight, decides what can outvote what

A weight scales a term. What it can *do* to the ranking is the weight times the range the term can
actually reach, and those two orderings come apart immediately, because the terms are not the same
kind of number:

| kind | example | attainable range |
|---|---|---|
| bounded confidence | `1 − ipTM`, `1 − mean pLDDT` | **[0, 1]** |
| a PAE mean | `interface PAE` | **[0, ~31]** — AF2's bin maximum |
| a contact `−log p` | `−log(clip(p, 1e-8, 1))` | **[0, 18.42]** — the clamp sets the ceiling |
| a ratio | `a² / max(b − c, ε)` | **unbounded**, and singular at `b = c` |

Measured on a real binder pipeline whose weights read `i_ptm: 1.0`, `i_pae: 0.5`, `con: 0.1`:

| term | weight | weighted span |
|---|---|---|
| `i_ptm` | 1.0 | **1.00** |
| `con` | 0.1 | **1.84** |
| `i_pae` | 0.5 | **15.50** |

The term with the **largest** weight has the **smallest** influence. Nothing in that recipe is
wrong term by term; the ordering is simply not the one the weights suggest, and no amount of
reading the weight list reveals it.

**So run a range audit before summing.** For each term write down the range it can actually reach,
multiply by its weight, and sort by that. If the order surprises you, the weights are not saying
what you think. A bounded [0, 1] term summed against an unbounded one cannot win an argument with
it: the worst possible interface confidence costs 1.0, while a single contact term moves 1.84.

**Ratio terms deserve their own look.** A term shaped `a² / max(b − c, ε)` has two failure regions,
and the clamp hides both: it goes singular as `b → c` — with `ε = 1e-8` and `a` reaching 18.42 the
term reaches ~3.4e10, so after a 0.1 weight it still dwarfs every other term combined — and below
`b = c` it is pinned flat at the clamp, so the thing it was meant to discriminate stops changing
the number at all. A term that is either astronomical or constant is not measuring anything in
between.

Prefer a bounded transform, or rescale each term to a common span before weighting — and if you
rescale, say so in the recipe, because two campaigns that rescaled differently are not comparable.

## Developability liabilities: compute them, do not narrate them

These are sequence motifs. A regex is strictly more reliable than asking a model to scan a
125-residue string, and the temptation to describe the screen in a prompt instead of running it is
the most common way this gets faked:

| Liability | Pattern | Note |
|---|---|---|
| N-glycosylation sequon | `N[^P][ST]` | the canonical one; P at position 2 blocks it |
| Deamidation | `N[GS]` | NG fastest; NS, NT slower |
| Isomerization | `D[GS]` | DG fastest |
| Acid cleavage | `DP` | |
| Unpaired cysteine | count parity of `C` per chain | an odd count is the flag |

Met/Trp oxidation is **not** a pure sequence motif — it depends on solvent exposure, so it needs the
structure, not a regex. Say so rather than shipping a regex that pretends otherwise.

Run these on the CDRs first: a liability in a CDR is a liability in the paratope. And keep the
decision rule monotone — any High-risk dimension fails the candidate; do not average risk scores,
because averaging lets one serious flag be diluted by several clean ones.

## What none of this proves

Every number above is computed from a **predicted** structure. If the co-fold is wrong, the gate,
the contact fraction and the confidence are all confidently wrong together, and they will agree with
each other because they are reading the same fiction. The panel ranks designs against one another;
it does not tell you that any of them binds. Computational results require experimental validation,
and the honest deliverable from a design campaign is a ranked shortlist with its evidence, not a
hit.

## Provenance

The thresholds and the weighting conventions here were read out of
[aurekaresearch/OpenDDE-Harness](https://github.com/aurekaresearch/OpenDDE-Harness) at `0388d2a`
(`core/gate.py`, `servers/backends/loss_confidence_scorer.py`, `servers/backends/loss_objective.py`,
`servers/backends/ipsae.py`, `agents/phases.py`) — an open-source antibody-design harness whose
numbers are worth borrowing even where its implementation is not. The `d0` form is the TM-score
one; the sequence lengths above are from `docs/examples/crlf2_quickstart.yaml` in that repo.
Treat every threshold as a *defensible default*, not as law: they suit a VHH-on-antigen campaign
and should be re-derived for a different modality.

## See also

- `antibody-numbering` — which CDR residues these fractions are computed over, and why a CDR length
  of 0 is a parse failure
- `binder-benchmarking` — whether a model's own score can be trusted for triage at all
- `protein-binder-campaign` — the de novo miniprotein protocol, including its ipSAE:sc_DockQ ranking
