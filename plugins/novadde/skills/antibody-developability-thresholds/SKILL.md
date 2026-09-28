---
name: antibody-developability-thresholds
description: Use when a developability number needs a threshold — TAP's five descriptors (total CDR length, PSH, PPC, PNC, SFvCSP), where the amber and red lines actually sit, and whether a given flag transfers to your molecule. This is the threshold half of `antibody-liabilities`, which computes sequence motifs, and of `antibody-interface-metrics`, which owns what a hit means. Triggers include "is this CDR total too long", "what is a bad PSH", "TAP flagged my antibody", "what developability thresholds should I gate on", "does TAP apply to a nanobody", "compute SFvCSP".
---

# Developability thresholds

`antibody-liabilities` computes sequence motifs. `antibody-interface-metrics` says what a hit
means. Neither carries a **threshold** for a surface or charge descriptor, because those come from
one place: the distribution of antibodies that actually reached the clinic.

TAP (Raybould *et al.*, PNAS 2019 **116**:4025; TAP2, *Commun Biol* 2024) is that distribution.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/tap_descriptors.py \
    --cdr-lengths H1=8,H2=8,H3=13,L1=6,L2=3,L3=9 --thresholds tap2-2024

python3 ${CLAUDE_SKILL_DIR}/scripts/tap_descriptors.py --selftest
```

Stdlib only.

## One of the five is computable from sequence. Know which.

| | needs | |
|---|---|---|
| **Total CDR length** | IMGT numbering | the script computes and flags it |
| **PSH** patches of surface hydrophobicity | a 3D Fv model | refused |
| **PPC / PNC** patches of positive / negative charge | a 3D Fv model | refused |
| **SFvCSP** structural Fv charge symmetry | a 3D Fv model | refused |

**SFvCSP is the trap, and it is worth slowing down for.** It reads as a sequence quantity — net VH
charge times net VL charge — and it is not. The **S** is for *structural*: the sums run only over
residues that are **surface-exposed and not locked in a salt bridge**. The sequence-level cousin is
**FvCSP** (Sharma *et al.*), a *different metric with different values* — TAP's own galiximab
example is FvCSP **0** against SFvCSP **+2.0**. Compute a charge product from sequence, call it
SFvCSP, compare it to the SFvCSP threshold, and every step looks right.

In practice TAP still takes only two sequences: it builds the model itself (ABodyBuilder2 /
ImmuneBuilder since 2023-01-30). The input is sequence; the *metric* is structural.

## Total CDR length is IMGT, and ours is Chothia

TAP numbers with **IMGT** and uses IMGT CDR spans — **27–38, 56–65, 105–117** — and the patch
metrics are summed over a "CDR vicinity" of those residues **±2 either side** plus surface-exposed
residues within 4.5 Å.

`antibody-numbering` in this repo publishes **Chothia** windows. A total computed from those is a
different quantity and **must not be compared against these thresholds**. The script therefore takes
lengths rather than sequence windows, and requires all six: the papers never enumerate which CDRs
the total covers, but the reported mean of **48.02 ± 3.77** over 242 CSTs is only reachable with all
six, so a partial sum is a different number wearing the same name.

North appears in the TAP papers only for canonical-form clustering. It has nothing to do with any
of the five metrics — a natural confusion, since North is the usual choice elsewhere.

## Amber is a percentile. Red is not.

- **amber** = the 0–5th or 95–100th percentile of the clinical-stage set.
- **red** = **outside the entire observed range** of that set. Not a percentile.

That gives you a free correctness check, which `--selftest` applies to every set it ships: the outer
amber bound and the red bound must be **the same number**. Where they are not, someone has
mistranscribed a threshold — and that is not hypothetical. The live TAP page's **PPC (4.20 vs 4.24)
and PNC (4.43 vs 5.67)** rows violate it, leaving an unflagged dead zone; every other published
version has them equal. Total CDR length is unaffected.

## There are three published threshold sets and they disagree

| set | reference | total CDR length |
|---|---|---|
| `2019` | 242 CSTs, ABodyBuilder1 | amber 54–60, red > 60, **no lower bound published** |
| `tap2-2024` | 664 CST Fvs, ABodyBuilder2 | amber 37–42 and 55–63, red < 37 or > 63 |
| `live-2025` | 851 post-Phase-I Fvs | amber 37–42 and 55–65, red < 37 or > 65 |

A total of **64** is red under `tap2-2024`, **amber** under `live-2025`, and red under `2019`. So
the set travels with the flag, and the script refuses to pick one silently.

**The thresholds are modelling-method-specific.** The 2019 work measured a systematic bias toward
higher PSH in models than in crystal structures, which is why it compared models only to models.
OPIG warns against comparing scores across modelling versions; a PSH from your own pipeline is not
comparable to a TAP-reported PSH unless the structures were built the same way.

The 2019 lower bound for total CDR length **is not published** — Table 1 says it flags the bottom
5%, Table 2 prints no lower region, and neither does SI Table S3 or S4. The script leaves a low
total unflagged under that set and says so, rather than inventing a bound.

## It does not transfer to a VHH

TAP2's own inclusion criteria exclude single-domain antibodies outright: entries were filtered to
those "that have complete variable regions (Fvs, i.e. no single domain antibodies were carried
forward)". So:

- **SFvCSP is mathematically undefined for a VHH** — there is no VL to multiply by.
- The other four are calibrated on a **two-domain** surface. A VHH's total CDR length is drawn from
  a different distribution entirely, and a nanobody scored against a 37–63 window built from paired
  Fvs is being compared with molecules it is not one of.

Neither paper discusses nanobody transfer, so this is a limit to state rather than a correction to
apply. Much of this lab's work is VHH; that makes this the most load-bearing paragraph here.

There is also a known **λ/κ bias**: in the 242-CST models, κ PSH was 120.89 ± 15.10 against λ
142.03 ± 19.09. That gap is the entire subject of TAP2.

And the authors' own caveat, which outranks everything above: *"the thresholds themselves should not
be interpreted as hard-and-fast rules."* They are the shape of a distribution, not a specification.

## Do not source a pI window from Jain 2017

It is the obvious citation and it does not contain one. Jain *et al.*, PNAS 2017 **114**:944 reports
twelve biophysical assays over 137 clinical-stage antibodies — PSR, AC-SINS, CSI-BLI, CIC, HIC,
SMAC, SGAC-SINS, BVP, ELISA, accelerated-stability SEC, Tm, HEK titer. **"pI", "isoelectric" and
"charge" do not appear in the full text.** Its Table 1 "worst 10%" thresholds are derived from the
48 approved antibodies and carry no pI row.

If you need a measured window, Goyon *et al.* 2017 (*J Chromatogr B* **1065-1066**:119) reports
**pI 6.1–9.4** by icIEF across 23 approved mAbs — small n, but measured, on approved drugs. Cite it
as that, not as Jain.

`antibody-liabilities` computes pI with the **EMBOSS** pKa set. TAP assigns fixed charges instead
(Asp −1, Glu −1, Lys +1, Arg +1, **His +0.1** at pH 7.4). Two different charge models: do not feed
one into the other's threshold.

## What is not established

Stated because a manual that hides its uncertainty is worse than one that does not have any:

- The **2019** anchor count. Only TAP2's ±2 is sourced; the 2019 paper says "anchor residue" with
  no number.
- The CDR-vicinity radius is **4 Å in 2019 and 4.5 Å in TAP2**. Whether that is a real protocol
  change or a loose restatement is not established — do not write one as covering both.
- Whether PPC and PNC restrict the pair sum to **same-sign** residues. The names and the |Q(R)|
  substitution make it near-certain; the Methods never say it.
