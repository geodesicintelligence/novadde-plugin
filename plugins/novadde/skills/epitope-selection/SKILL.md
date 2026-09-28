---
name: epitope-selection
description: Use when choosing WHERE on a target a binder or antibody should bind — picking hotspot residues, reading UniProt site annotations, or deciding whether a proposed epitope is reachable at all. Every other design skill here begins after an epitope exists; this one is about choosing it, and about the annotation trap that aims a design at a surface no antibody can reach. Triggers include "pick hotspots for this target", "which residues should the binder contact", "is this a good epitope", "UniProt says the binding site is here", "what should I target on HER2".
---

# Choosing an epitope

`protein-binder-campaign` and `binder-benchmarking` start from a target **and an epitope**.
Choosing the epitope is upstream of both, and it is where a design is most cheaply ruined.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/epitope_candidates.py --accession P04626
python3 ${CLAUDE_SKILL_DIR}/scripts/epitope_candidates.py \
    --accession P04626 --residues 300,845
python3 ${CLAUDE_SKILL_DIR}/scripts/epitope_candidates.py --selftest
```

Stdlib only. Reads UniProt REST; `--selftest` is offline.

## The annotation trap

UniProt's `Binding site` and `Active site` features annotate **catalytic chemistry**. On a
single-pass receptor that chemistry is almost always **intracellular**. So the features that read
most like "the functional part of the protein" are exactly the ones a binder cannot reach.

HER2 — `P04626`, the canonical antibody target — verified against live UniProt on 2026-09-15:

```
Topological domain   23-652      Extracellular
Transmembrane        653-675
Topological domain   676-1255    Cytoplasmic
Active site          845         Proton acceptor
Binding site         726-734, 753
```

**Every annotated site is cytoplasmic.** Trastuzumab binds domain IV, roughly 563–626 — which
carries no site annotation at all. An agent asked to "pick hotspots for a HER2 binder" that reaches
for `Binding site` aims the design at the kinase ATP pocket, on the far side of the membrane.

IL1R1 (`P14778`) is the same shape: Active site 470, cytoplasmic 357–569.

The script classifies every annotated feature by the topological domain it falls in, and refuses a
residue on the wrong side.

## What the topology gate is and is not

It is **necessary, not sufficient**. Passing it means the residue is on the reachable side of the
membrane. It says nothing about whether the epitope is a good one — that still needs a known
therapeutic epitope, a co-crystal, or a surface patch you have reason to believe in.

`Mutagenesis` features are the more useful annotation when they exist, because their descriptions
often record an actual binding or interaction experiment rather than catalysis. They still have to
pass the same gate: on HER2 the script finds mutagenesis at 317–318 and 611 (extracellular, usable)
alongside 687, 706 and 712 (cytoplasmic, not).

**No topological domains annotated is not a pass.** It means either a soluble protein, where the
question does not arise, or an entry whose topology was never curated. Those are different and the
script cannot tell them apart, so it returns `null` rather than `true` and says so.

## Two rules that need a structure, and their numbers are not calibrated

Once you have candidates, two checks belong to the structure rather than the annotation:

- **Compactness.** A binder grips one local patch, not a scatter. Drop candidates far from the
  densest cluster's centroid, cap the set, and prefer at least two. The source this came from uses
  30 Å, a cap of 15, and a floor of 2.
- **Numbering.** Validate every residue against the coordinate file and read back its three-letter
  identity. AlphaFold DB models are numbered as UniProt; experimental and cropped PDB entries are
  frequently offset, and an off-by-N hotspot list silently designs against the wrong surface.

**Treat those thresholds as conventions, not calibration.** They come from NVIDIA's
`bionemo-agent-toolkit` (Apache-2.0), which publishes no benchmark supporting them — and whose own
two binder workflows disagree with each other on the downstream gates (ipTM ≥ 0.8 in one, ≥ 0.65 in
the other, for the same decision). The topology trap above is reproducible and was verified here
independently; these numbers are someone's working defaults.

## Where this sits

`antibody-numbering` owns CDR windows and renumbering — use it for the antibody side. This skill is
about the **target** side. `antibody-interface-metrics` judges an interface once it has been
predicted; this runs before anything has been designed.
