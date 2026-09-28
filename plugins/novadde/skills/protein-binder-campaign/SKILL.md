---
name: protein-binder-campaign
description: Run a de novo miniprotein binder design campaign following the Anthropic claude-protein-binder-design release prompts. Use when asked to design binders against a protein target end to end, to reproduce or adapt that campaign's methodology, or when questions come up about its roster, gates, scoring instrument (ipSAE + sc_DockQ), selection caps, or deliverables. Covers 16 single-target campaigns (EGFR, PD-L1, TNFa, TREM2, TrkA, VEGF-A, GDF-8 mature and latent, IL-7Ra, BBF-14, BHRF1, MBP, Cas9, RBX1, Nipah-G, 15-PGDH) plus the 14-target multi-target campaign.
---

# De novo miniprotein binder design campaign

This skill wraps the campaign prompts released with the
[Anthropic/claude-protein-binder-design](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design)
dataset. The prompts are reproduced verbatim as run — they are the specification,
not a summary of one.

## What is here

| path | what it is |
|---|---|
| `references/multi_target_binder_design_prompt.md` | the 14-target, 48 h / $50k campaign prompt |
| `references/single_target/<TARGET>.md` | 16 single-target, 24 h / $10k prompts (shared template, target swapped) |
| `references/kickoff/{single,multi}_target_kickoff.md` | the T0 user message that starts a campaign |
| `references/figures/Figure {1,2}.jpg` | Local Composition Perplexity (LCP): definition and results |

Each prompt is ~112 KB (~28k tokens). Read only the one you need. The
single-target prompts differ from each other in about 5% of their lines — the
task line, the target-definition paragraph, the competition references, and the
oligomer clause of scoring item 7 — so reading a second one to compare is
usually wasted.

## How to use it

1. Pick the prompt: one `references/single_target/<TARGET>.md`, or the
   multi-target prompt. Read it in full before doing anything else.
2. Load it as the agent's system context, and attach the same file plus both
   figures to the first user message.
3. Send the matching `references/kickoff/*.md` as that first user message. T0 is
   its timestamp.
4. Fill the operator placeholders before launch: `<campaign-slack-channel>` /
   `<SLACK_CHANNEL_ID>`, `<Campaign Deliverables Folder>` /
   `<DRIVE_DELIVERABLES_FOLDER_URL>`, and the emergency-contact line
   (`<operator Slack handle>`, `<operator email>`, `<operator phone>`).

The figures are not decoration: LCP is a mandatory sequence-design restraint and
the prompt requires the per-position penalty be implemented exactly as Figure 1
defines it, with `lcp_score` recorded per designed sequence.

## What the prompts assume that this workspace does not have

The prompts were written for the Claude Science agent harness and are reproduced
unchanged. Before running one, decide what stands in for each of these — none is
present here:

- **Harness**: `host.delegate`, `host.compute`, `submit_gate`,
  `wait_for_notification`, `host.current_model()`.
- **Compute**: an operator-funded Modal account, sandboxes tagged
  `claude-science-project`, four campaign Modal volumes (`state`, `ledger`,
  `out`, `novelty`).
- **Reporting**: a Slack channel and a Google Drive deliverables folder.
- **The External Resource Corpus** (`corpus/`, 317 files, 1.16 GB): every paper
  and web page the prompts cite. Not bundled here — it is in the dataset at
  `prompts/protein_binder_design_prompts_release.zip`. Every "corpus folder"
  reference in a prompt (`07 Prompt-Cited Papers`, `06 Prompt Figures`,
  `02 ProteinBase`) is a subfolder of it. Fetch it if you intend to run a
  campaign for real; the prompts tell the agent to prefer the corpus copy over a
  paywalled link.

## Roster coverage from the geodesic MCP

The geodesic MCP server on this workspace covers part of the prompt's tool
roster. Verify against `describe_model` rather than trusting this table — it is
a starting map, not a contract.

| prompt roster | geodesic |
|---|---|
| RFdiffusion3\* | `rfdiffusion3` |
| BoltzGen\* | `boltzgen` |
| Proteina-Complexa\* | `proteina` |
| BoltzDesign1 | `boltzdesign` |
| Protein Hunter | `proteinhunter` |
| FreeBindCraft\* | `bindcraft` — the deployment is already PyRosetta-free, but 15 of 54 filter thresholds are nulled as a result |
| SolubleMPNN | `proteinmpnn`, soluble weight set |
| Protenix v2 | `protenix`, mode `protenix-v2` — but see below: **disabled on this deployment** |

**The gap that matters**: **none** of the three mandatory ranking arms runs here.
**ESMFold2-Full** and **ESMFold2-Fast** have no geodesic equivalent — geodesic's
`esmfold` is the original ESMFold, which the prompt explicitly calls superseded
and out of scope as an instrument. The third arm is no better off: protenix's
`protenix-v2` mode ships `disabled: true` in the live spec — "The Protenix-v2
weights are not available to this deployment" — and protenix's other modes are
not v2. So all three arms need a logged substitution, not two.

There is **no local route to ESMFold2**. This workspace runs protein models on
geodesic only (see the `geodesic` skill), and geodesic does not have it. Take the
prompt's own escape hatch: bring up one independent-lineage co-folder per missing
arm — AlphaFold-Multimer-v3, then AF3 code + OpenFold3 weights, then Chai-1, then
Boltz-2/Boltz-1, all with target-chain MSAs — and record which arm each stood in
for. Substitutes must come from a different lineage than the surviving arms and
must represent any dossier-flagged cofactors.

Do not quietly re-route this to a hosted ESM API. It would work, but it sends
every design sequence to a third party, and this workspace was set up to keep
them local.

Also absent from geodesic and needed by the prompts: RFdiffusion v1, PXDesign,
Genie3, Mosaic, FoldCraft, HalluDesign, SolubleCaliby, Protpardelle-1c,
MMseqs2 (UniRef90 novelty gate), and DockQ. `rfdiffusion` and `pxdesign` were
served until 2026-09-08 and are not any more — see `geodesic` for why, and
distrust any older note that maps either one.

Three of those are **asterisked** structure-design methods — RFdiffusion v1,
PXDesign and Genie3 — so each carries the 50-backbone-per-target floor, and the
prompt says outright that skill availability is not valid grounds to skip an
asterisked method. Four of the seven have a local route (`rfdiffusion3`,
`bindcraft`, `boltzgen`, `proteina`); the other three need a logged deviation per
target, not a quiet reallocation.

**ipSAE is not one of them.** The `ipsae-calculate` skill in this repo computes
it from a PAE matrix and its matching structure with NumPy alone — no network,
no GPU — so the prompt's TOOL-BRINGUP of the DunbrackLab reference `ipsae.py` is
work already done. The prompt's own rule is *"unless a skill exists"*; one does.

**But it is the pairwise form, and the prompts need the union-mask form for
multimeric targets.** The prompt defines `ipSAE_min` on a multimeric target as a
*single* call with `mask_target` = every residue where `asym_id != B` — the union
of protomers T1..Tn, with `n0`/`d0` re-derived from the union's size — and says
that call **replaces** the stock pairwise loop over `(B, Ti)`. `ipsae.py` is the
stock loop: `--binder-chains`/`--target-chains` scores each crossing chain pair
separately and reports the best. Each call therefore sees one protomer's
qualifying-partner count as `n0res`, not the union's, so it returns a different
number — not a rounding difference. Monomeric targets need nothing extra; every
multimeric one needs that variant written before its `ipSAE_min` column means
what the prompt says it means.

**No wet lab.** The prompts end in an order sheet of 30 designs that a foundry
synthesizes and assays by BLI/SPR — Adaptyv, whose competitions the prompts cite
throughout. Nothing in this workspace can do that. Geodesic is in-silico only,
and the Adaptyv Foundry skill was deliberately removed. A campaign run here stops
at the ranked sheet; ordering is a separate, external, billed step someone has to
arrange.

Other skills here that the campaign leans on: `geodesic` (every model that runs
locally), `ipsae-calculate` (the scoring instrument's ipSAE half, with the caveat
above) and `antibody-interface-metrics` (what those numbers mean),
`paper-lookup` (the required per-target literature review), `biopython`
(structure and sequence handling), and `glycoengineering` (N-glycosylation sequon
liability scanning).

## Provenance

Prompts, kickoff messages and figures retrieved 2026-08-27 from
`Anthropic/claude-protein-binder-design` at `prompts/prompts/`, unmodified.
Dataset licence: CC BY 4.0. Figures 1 and 2 are shared with permission from
Richard Shuai. The dataset also carries the campaign's wet-lab and in-silico
results (`data/`) and predicted structures with PAE (`structure_and_pae/`),
neither of which is copied here.
