---
name: antibody-numbering
description: Use when antibody residue numbering, CDR definitions, or chain conventions matter — designing CDRs, calling rfantibody/boltzgen, profiling CDR lengths, or interpreting a CDR length that came back as 0. Triggers include "which CDR residues", "Chothia or IMGT", "what numbering does this model want", "CDR length looks wrong", "H3 is 0", "renumber this Fab".
---

# Antibody numbering across the lab's tools

**The one invariant worth memorizing:**

> Residue numbering is not uniform across the platform, and getting it wrong designs against the
> wrong surface **with no error**.

Nothing validates that the residue indices you sent mean what you thought. A job with the wrong
convention runs to completion, burns GPU hours, and returns confident scores for the wrong epitope.
Check the convention before every submission that names residues.

## Which convention each consumer wants

| Consumer | Residue numbers are… |
|---|---|
| `boltzgen`, `proteinhunter` | **1-based ordinals within the chain** |
| most other entries | the uploaded file's **own numbers** |
| `app/registry/targets.py` | carries **both spellings** for every bundled target |

Framework upload format differs too, and this one *does* error:

- **`rfantibody` takes HLT-formatted PDB only** — chains must be H and/or L. It bundles VHH and Fv
  templates, so no upload is strictly required.
- **`boltzgen` takes any ordinary PDB/CIF in any numbering** — ANARCI resolves it — but bundles no
  framework, so an upload is required.

Both support VHH, scFv and Fab. **A Fab is designed as its Fv in both**, since only the variable
domains are ever designed. Their twelve CDR field keys (`designH1`…`lengthL3`) are **identical by
design**, so one params dict goes to either — that is enforced by a generator in `boltzgen.py`, not a
coincidence to rely on loosely.

**Authority:** `model_platform_api/docs/calling-antibody-models.md` is the complete, GPU-verified
calling contract — HTTP shape, per-CDR fields, measured runtimes, and the gotchas. Read it before a
first submission, and discover the fields programmatically rather than hardcoding that document.

## CDR definitions used here

**Chothia numbering with Chothia boundary definitions:**

| | H1 | H2 | H3 | L1 | L2 | L3 |
|---|---|---|---|---|---|---|
| window | 26–32 | 52–56 | 95–102 | 24–34 | 50–56 | 89–97 |

**Length counts occupied residues including insertion codes** — an H3 running 100A–100K counts all
of them.

Sequences for profiling come from deposited **SEQRES**, re-numbered with ANARCI. **ATOM records are
never read**, so unresolved density cannot silently shorten a loop.

## A CDR length of 0 is a parse failure, not a value

A length is only reported where the numbering covers the **whole** Chothia window. Two failure modes
used to be recorded as length 0, and both now drop the chain and get counted in QC instead:

1. **An empty Chothia numbering** — ANARCI finds the domain but the scheme cannot express an
   ultralong CDR-H3.
2. **A construct numbered from mid-domain.**

If you see a 0, treat it as "this chain did not parse", never as "this loop is empty".

**Consequence to state whenever quoting an H3 distribution: the upper tail is truncated by
construction.** Bovine ultralong-H3 antibodies are absent from the profile, not rare in it.

## The dedupe unit is the molecule, not the chain

For Fab/Fv/scFv the unique unit is the **`(heavy Fv, light Fv)` pair**, taken from the SAbDab summary
row that deposited them together — so all six CDRs share one denominator, and one heavy sequence
solved against three different lights is **three antibodies**. A pair whose chains carry different
taxids is bucketed `chimeric`. Single-domain types (VHH, VNAR, SD-L) have no partner and dedupe per
chain.

Counting per chain instead double-counts heavies and gives H and L different denominators.

## ANARCI

- **Python 3.11 or 3.12 only.** ANARCI's multiprocessing path fork-bombs on 3.14 — this is why
  `antibody-profiling` pins `requires-python = ">=3.11,<3.13"`. Don't raise that ceiling.
- ANARCI is what lets `boltzgen` accept arbitrary numbering; it is also what fails to express an
  ultralong H3 in Chothia.

## Before trusting any number from the profile

Read `antibody-profiling/outputs/qc/qc.md` first — its caveats are load-bearing:

- `vhh` means SD-H and **includes engineered human heavy-only domains**;
- synthetic constructs are a large bucket;
- **SAbDab is a structure database, not a repertoire sample** — frequencies in it are frequencies of
  what got crystallized.

## Where the authorities live

| Question | Read |
|---|---|
| How to call the antibody design models | `model_platform_api/docs/calling-antibody-models.md` |
| What each model does, and its numbering | `model_platform_api/models/README.md` |
| How the CDR length profile was built | `antibody-profiling/README.md` + `outputs/qc/qc.md` |
| Field keys and validation as shipped | `GET /api/models/<slug>` — the authority over any document |
