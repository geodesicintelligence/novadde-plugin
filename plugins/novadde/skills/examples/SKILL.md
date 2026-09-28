---
name: examples
description: The three worked requests NovaDDE's own home screen offers - a bounded binder campaign, an epitope comparison, and a go/no-go lead decision. Use when someone wants to see what this agent is for, or wants a well-formed request to start from.
disable-model-invocation: true
---

# What a good request to NovaDDE looks like

These are the three starter prompts from NovaDDE's home screen, verbatim. Offer them as a list,
run the one the user picks, and change nothing in it without saying what you changed: each is
written to be answerable, and the closing "say what this does not establish" clause in the last two
is the point of them rather than decoration.

## 1. Design an IL7RA binder (runs GPU jobs)

> Design an 80-residue protein binder against the human IL-7 receptor alpha ectodomain. Fetch PDB
> 3DI3 and retain chain B (author residues 17-209). Target retained-chain positions 42, 64, and 123,
> corresponding to author residues 58, 80, and 139.
>
> Run this through the geodesic MCP server. Call describe_model("boltzgen") first and build the
> submission from the example it returns rather than from memory, then submit_job and poll with
> get_job. Note that boltzgen indexes residues as 1-based chain ordinals, not author numbering, and
> gets this silently wrong if you pass the wrong convention - state which numbering you used and
> show the mapping.
>
> Run one bounded campaign with at most 20 designs, diversity budget 8, base random seed 40, and
> stop once at least one candidate passes every fixed filter. Return the ranked manifest, FASTA, top
> candidate structures, the complete filter funnel, and a precise claim boundary. If no candidate
> passes, report that outcome without relaxing thresholds - for this platform an empty pass set is a
> normal result, not a failure.

## 2. Can PD-L1 blockade spare CD80? (no GPU)

> Can a differentiated anti-PD-L1 antibody block PD-1 while minimizing disruption of PD-L1/CD80?
> Compare the PD-1/PD-L1 complex 4ZQK with the atezolizumab, durvalumab, and avelumab complexes
> 5XXY, 5X8M, and 5GRJ.
>
> Use a 5 A heavy-atom cutoff to report the exact PD-L1 interface residues in each structure, and
> search Europe PMC for functional evidence about the PD-L1/CD80 interaction. Deliver: (1) an
> observed-vs-inferred evidence table with stable identifiers, (2) a recommended epitope region or
> an explicit no-go, (3) escape and cross-reactivity risks, and (4) three discriminating experiments.
>
> Do not invent an antibody sequence and do not run GPU tools.

## 3. Which IL7RA designs enter SPR? (no GPU)

> Should IL7RA-D17, IL7RA-D05, both, or neither advance from in-silico screening to expression and
> SPR? Both are 80-residue strict-filter passes against PDB 3DI3 chain B with full coverage of
> target positions 42, 64, and 123.
>
> D17: interaction PAE 4.27843 A, pLDDT 0.906, design-folding RMSD 0.80523 A, refold RMSD 1.44764 A,
> and 17 site-contact pairs.
> D05: interaction PAE 4.39403 A, pLDDT 0.899, design-folding RMSD 1.04649 A, refold RMSD 0.82779 A,
> and 21 site-contact pairs.
>
> No expression, monomer/aggregation, SPR, selectivity, or cell data exist. Make a concrete
> portfolio decision, state what the computation does and does not establish - interaction PAE and
> pLDDT are self-consistency measures, not affinity - define the smallest ordered assay plan with
> quantitative stop/go criteria, and identify the evidence that would change the decision.
>
> Do not run GPU tools.

The first one spends real GPU time. Lay out exactly what you are about to submit and get an explicit
yes before you submit it, the same as for any other request.
