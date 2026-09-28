---
name: antibody-liabilities
description: Use when an antibody or nanobody sequence needs the liability and charge screen actually run rather than described — deamidation, isomerisation, Asp-Pro, N-glycosylation sequon, unpaired cysteine, pI, hydrophobic runs. This is the executable half of `antibody-interface-metrics`, which owns what the hits mean. Triggers include "screen these designs for liabilities", "any NG sites in H3", "what is the pI of this VHH", "which of these 30 designs do I drop", "run the liability scan".
---

# Antibody liabilities

`antibody-interface-metrics` says of these motifs: *compute them, do not narrate them.*
This is the compute half. That skill owns what a hit means and how it should weigh on a
decision; this one owns getting the positions right.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/scan_liabilities.py <SEQUENCE> --name VHH-07 \
    --cdr H1=25:32 --cdr H2=50:57 --cdr H3=96:107
python3 ${CLAUDE_SKILL_DIR}/scripts/scan_liabilities.py <SEQUENCE> --json     # a row per design, for a table
python3 ${CLAUDE_SKILL_DIR}/scripts/scan_liabilities.py --selftest            # known answers, before you trust it
```

Stdlib only — it runs in your kernel with nothing installed, no network, no GPU.

## Give it the CDRs, or it will say it could not

The scanner never guesses IMGT or Chothia windows. Without `--cdr`, every hit is labelled
`framework-or-unassigned` and the header says so, because a liability attributed to residues
nobody designed is worse than one that admits it does not know which those are.

Ranges are **zero-based inclusive**, the convention the design YAML uses. Take them from the
YAML you launched with, or from `antibody-numbering`, which is the authority on the windows
and on where the conventions disagree.

This matters more than it looks: the whole decision rule in `antibody-interface-metrics` turns
on CDR versus framework, and without `--cdr` this tool cannot supply that axis.

## Reading the output

`severity` orders a review queue — `high` before `moderate` before `low`. It is not a
probability and it must not be summed; three `low` hits are not one `moderate`. The monotone
rule lives in `antibody-interface-metrics` and it applies here: one serious flag is not
diluted by several clean ones.

`pi` carries the pKa set it was computed under (`EMBOSS`). Two pI figures from different sets
differ by a few tenths and are not comparable, so the set travels with the number rather than
being implied. A computed pI is not a measured one, and the gap widens on unusual sequences.

`cysteines.unpaired_by_parity` is **parity only**. An odd count in a VHH is a real flag. In a
chain that pairs with another it may be the interchain bond doing its job — the count cannot
tell those apart, and neither can this script.

`hydrophobic_runs` are consecutive residues with a positive Kyte-Doolittle value, length 4 or
more. An observation about the sequence, not an aggregation prediction. A long run inside H3
is worth a look; the same run in framework is usually a beta strand.

## What it deliberately does not emit

**Met and Trp oxidation.** Oxidation is not a pure sequence motif — it turns on solvent
exposure, which a sequence does not know. An `M` row sitting in the same table as an `NG` row
reads as a finding, and `antibody-interface-metrics` rules on it: *say so rather than shipping
a regex that pretends otherwise.* If you need the exposure question answered, it needs the
structure. `--selftest` asserts the absence so it does not drift back in.

**A verdict.** It reports positions and classes. Nothing here ranks designs, and nothing here
decides. For what to do about a sequon in particular, `glycoengineering` owns that.
