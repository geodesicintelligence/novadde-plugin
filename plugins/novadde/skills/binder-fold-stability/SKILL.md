---
name: binder-fold-stability
description: Use when a designed binder scores well in complex and you need to know whether it is actually a folded, on-target molecule — the apo/holo check. Covers folding the binder alone and measuring apo↔holo Cα RMSD, reading apo pLDDT without falling for the scale and B-factor traps, and measuring hotspot contact under the three incompatible definitions of "contact". Triggers include "is this binder stable on its own", "apo holo RMSD", "did it bind the hotspots I asked for", "binder pLDDT", "my design has good ipTM, is it good".
---

# Is the binder a molecule, or only a complex?

`antibody-interface-metrics` and `ipsae-calculate` both score the **interface**. A design can
pass every interface gate and still be a disordered peptide that only folds because the target
is holding it. That failure is invisible to ipTM, to ipSAE, and to every contact metric —
they are all computed on the complex, where the binder is folded by construction.

So take the target away and fold the binder alone.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/apo_holo_rmsd.py \
    --apo apo.pdb --holo complex.pdb --binder-chains A --plddt --cutoff 2.5

python3 ${CLAUDE_SKILL_DIR}/scripts/hotspot_contacts.py \
    --structure complex.pdb --binder-chains A --target-chains B \
    --hotspots 557,560,561 --definition heavy-5

python3 ${CLAUDE_SKILL_DIR}/scripts/apo_holo_rmsd.py --selftest
python3 ${CLAUDE_SKILL_DIR}/scripts/hotspot_contacts.py --selftest
```

numpy + stdlib. Both `--selftest`s are offline.

## Two orthogonal questions

| Question | Metric | Why the interface score cannot answer it |
|---|---|---|
| Does the binder hold its fold alone? | apo↔holo Cα RMSD, apo pLDDT | Both are computed on the **apo** structure, which the complex score never sees |
| Did it bind where I asked? | fraction of hotspots contacted | Hotspot conditioning is a **request**. The folder may place the binder elsewhere and still report a confident interface |

## Do not import the published thresholds

The apo/holo gate comes from NVIDIA's `bionemo-agent-toolkit`
(`0e67a61`, Apache-2.0 / CC-BY-4.0). Its numbers are **not calibrated**, and the repository
does not agree with itself about them. For one decision — "is this ipTM good enough" — it ships
four different answers:

```
protein-binder-design/SKILL.md:66                   ipTM >= 0.8
complexa-binder-design/SKILL.md:139                 ipTM >= 0.65
complexa-binder-design/scripts/pipeline.py:109      AF2_IPTM_MIN = 0.70
complexa-binder-design/references/validation.md:71  "ipTM=0.62 < 0.70"
```

The last one is the same file as the second: line 43 tabulates `>= 0.65`, and line 71's own
worked failure example applies `0.70`. A doc that contradicts itself 28 lines apart is not a
calibration — it is a guess written twice.

The same split hits pLDDT, and it is the **scale** bug this skill's script guards against:
`protein-binder-design` gates `binder pLDDT >= 80` while `complexa-binder-design` gates
`>= 0.70`. Same quantity, two scales, one repository. Applied to the wrong file, the first
passes everything and the second fails everything — silently, because both are valid numbers.

Use these as **starting points you then calibrate on your own actives and decoys**, exactly as
`antibody-developability-thresholds` says of TAP. Written down for reference, not endorsed:

| Gate | Toolkit value | Where |
|---|---|---|
| apo binder pLDDT | ≥ 0.70 | `validation.md:46` |
| apo↔holo binder Cα RMSD | ≤ 2.5 Å | `validation.md:48` |
| hotspot contact fraction | ≥ 20% | `validation.md:49` |

**≥ 20% is very permissive.** A design that touches one hotspot in five passes it. If you
conditioned on five residues because you wanted five, say so in your own threshold.

## "Contact" means three different distances

The toolkit defines hotspot contact as **Cβ within 13 Å** (`validation.md:49`). That is not a
contact — it is the neighbourhood RFdiffusion-family models use for hotspot conditioning. Van
der Waals contact is ~4 Å. The script makes you name the definition, and reports which you used.

Measured on **1N8Z** (trastuzumab Fab + HER2), against the epitope published in Cho et al.,
*Nature* 2003 (HER2 557–561, 570–573, 593–603), with a 20-residue control in domains I–III:

| `--definition` | published epitope | control |
|---|---|---|
| `heavy-5` — any non-H atom pair ≤ 5 Å | 14/20 = **0.70** | 0/20 |
| `cb-8` — Cβ–Cβ ≤ 8 Å (CASP convention) | 15/20 = 0.75 | 0/20 |
| `cb-13` — Cβ–Cβ ≤ 13 Å (toolkit gate) | 20/20 = **1.00** | 0/20 |

All three separate epitope from control perfectly. But `cb-13` scores a **real, published,
crystallographically determined epitope at 100%** — it cannot distinguish a good epitope from a
merely nearby one. The six epitope residues that miss under `heavy-5` sit at 5.1–8.3 Å: inside
the epitope loops, side chains pointing away. That is why a published epitope is not a contact
list.

The cutoff here is inclusive (`<=`); the toolkit writes `<`. It differs only for a distance
landing exactly on the cutoff.

## The pLDDT column is not labelled

`--plddt` reads the B-factor column, because that is where folders write pLDDT. Two silent
failures, both handled by reporting rather than guessing:

- **Scale.** 0–100 or 0–1, detected from the values and stated as `detected_scale`; output is
  always normalised to 0–1 so a 0.70 gate means one thing.
- **Provenance.** In an *experimental* structure that column is the crystallographic B-factor,
  where **low is good** — the opposite direction. Nothing in the file says which it is.

The consequence, run on 1HEL (a 1.7 Å crystal structure of lysozyme — an excellent structure):

```
mean_plddt: 0.1365      fraction_below_0.70: 1.0      detected_scale: 0-100
```

It "fails" a confidence gate it was never on the scale of. The report carries an `assumed`
line saying so. Only pass `--plddt` for a predicted model.

## On this deployment

Read `geodesic` for the model roster and the submit/poll loop. Three things constrain this
workflow here, all measured:

1. **The apo fold is a second job.** Nothing produces it as a side effect of the complex
   prediction. Submit the binder sequence alone, then compare.
2. **The conditioning asymmetry is not expressible.** The toolkit wants the binder as
   single-sequence and the target with an MSA in the *same* prediction
   (`validation.md:12–15`). Protenix's mode is a whole-job flag, not per-chain — and
   `single-sequence` mode reliably OOMs on this deployment because it loads ESM2-3B. Run
   `msa` mode and record that both chains got an MSA; the apo binder fold is then more
   confident than the toolkit intends, which makes this gate **more** permissive, not less.
3. **The toolkit's `ipSAE_min ≥ 0.45` gate cannot be evaluated here.** It needs a PAE matrix
   and no model on this deployment emits one — see `ipsae-calculate`.

## What this does not measure

A contacted hotspot with a rigid apo fold is still not a binder. This is a **filter that
removes designs**, not evidence that the survivors work. Affinity, expression, and specificity
against a decoy are all downstream, and none of them are predicted here.
