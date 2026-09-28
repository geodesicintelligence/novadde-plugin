---
name: geodesic
description: Run protein design, structure prediction and structure/sequence validation on this deployment's own GPUs through the geodesic MCP server. Use for de novo binder design, antibody and nanobody CDR design, structure prediction of complexes and ligands, inverse folding, all-atom structure validation, and antibody humanness scoring. Also use when choosing which model fits a task, when a geodesic job fails, or when a request would otherwise go to a third-party protein API — geodesic runs on this deployment's own GPUs, and most models can be run with no egress at all — `novaatom` never can, and `protenix` has no offline mode that is known to run here. Also use for getting a result out of a finished job onto disk. Also use for getting a local file INTO a job when it is not a preset, a url or an earlier run's output.
---

# Geodesic: local protein models

Thirteen containerized models on this deployment's own GPUs. Nothing leaves the
network except where explicitly noted under **Data egress** below.

## The loop

1. `list_models` — the catalog, with `available` per model.
2. `describe_model(slug)` — the model's full parameter surface, and an `example`
   taken from its own bundled preset that is **a valid submission as-is**.
   Perturb that example rather than composing a submission from scratch.
3. `submit_job` — params from the example; for each file key pass a source as a
   flat string: `"preset:<the example's preset id>"`, `"url:<https url>"`,
   `"job:<id>#<artifact path>"` to feed an earlier run's output straight in, or
   `"stage:<id>"` for a file on your own disk — see **Getting a file in** below.
4. `get_job` / `list_jobs` — poll. Jobs take minutes to hours. Nothing blocks.
5. `get_stage_log(job, stage)` on failure — **the real error is at the end of
   it**. Read it before changing anything.
6. Read or download the outputs — see **Getting a result out** below.
   Which of the three tools you want depends on where the file is going.

`get_model_readme(slug)` is the long-form documentation: what a model does, what
it needs, how to read its outputs, and its known limits.

## Getting a result out

Three tools, and the choice is **where the file is going**, not how big it is.

| tool | cap | costs context? | for |
|---|---|---|---|
| `read_artifact` | 256 KB, **tail-truncates** and says so | yes | a log or a score table you are going to READ |
| `read_artifact_bytes` | 8 MB, **refuses** rather than truncate | yes, as base64 | the rare case needing exact bytes inside the conversation |
| `fetch_artifact` | none | **no** | anything going onto disk: structures, tables, a pool you keep |

`fetch_artifact(job_id, path)` returns `{path, size, sha256, url, header, curl,
expires_in_seconds}` and no bytes at all. **Run the `curl` it hands back** rather
than composing one: the ticket rides an `X-Artifact-Ticket` header, not the url,
so a command written from memory against the url alone answers 401.

```bash
curl -sS --fail-with-body -H "<header>" -o <dest> "<url>" && sha256sum <dest>
```

Compare that sum to the `sha256` the tool returned. The url is good for
`expires_in_seconds` and for that one file; afterwards it answers 404, which is
expiry and not a permissions problem — call the tool again for a fresh url.

**Do not fall back to `read_artifact_bytes` when a download fails.** It returns
the file as base64 through the conversation, and reproducing that into a heredoc
is what drops the connection: measured on a 34 KB CSV, twice, and that file was
the only result of the run missing from disk afterwards. Re-mint the url instead.

**No job on this deployment has been observed to write a PAE matrix.** Measured 2026-09-15 over
every job it holds: nine jobs, five of them completed BoltzGen runs with 14-16 artifacts each, and
not one `.npz` or `pae`-named file among them. A completed BoltzGen run returns `.cif` designs,
two metrics CSVs, a PDF overview and logs; `pae` appears only as a **scalar** in per-design metrics
(`"iptm":0.379, "ptm":0.777, "pae":9.676`), from which no matrix can be recovered.

`protenix` is now cleared too, and it **strengthens** the rule above rather than weakening it: a run
in the default `msa` mode completed here on 2026-09-15 and returned summary JSON with no PAE matrix
among its artifacts. That is one run in one mode — its `single-sequence` submissions ran out of GPU
memory before producing anything, and its `fast` mode has never been run here. `esmfold` is what is
left unknown rather than cleared: every job of its here failed before producing output. So read the
artifact list of the finished job rather than expecting a companion file. An earlier version of
this paragraph promised a `pae_<stem>.npz`; that contract came from `Geodesic-Bio-Agent`, which is
no longer in the image.

## Getting a file in

Five sources for a file field, and the choice is **where the file already is**.

| source | for | costs context? |
|---|---|---|
| `"preset:<id>"` | the model's own bundled example | no |
| `"url:https://..."` | a public database, from an allowed host | no |
| `"job:<id>#<path>"` | an earlier run's output, fed straight in | no |
| `"stage:<id>"` | **a file on your own disk**, via `stage_file` | no |
| `"content:<text>"` | a few lines you composed here | **yes, all of it** |

`content` is capped at 64 KB and refused above it, because it is not a transfer:
it is the whole file retyped by the model, token by token. Measured on a 124 KB
renumbered PDB — four attempts, every one dropped by the gateway before a job
existed, and the conversation died. The largest inline content that ever
succeeded here is 48 KB.

For anything you built locally, `stage_file` is the route, in three steps:

```bash
sha256sum target.pdb && wc -c < target.pdb     # 1. measure it
# 2. stage_file(path=..., size=..., sha256=...) -> returns a ready `curl`
curl -sS --fail-with-body -X PUT -H "<header>" --data-binary @target.pdb "<url>"
# 3. submit_job(..., files={"targetStructure": "stage:<stage_id>"})
```

Both numbers are signed into the ticket, so the upload can only be the bytes you
measured. A 204 and no output means it landed. The staged file is not consumed —
retry `submit_job` against the same id without uploading again.

**A file that exists only on your disk has no route but `stage_file`.** `preset`,
`url` and `job` all name something the server can already reach; `content` is the
model retyping it. That was the gap that killed the run above: the agent reasoned
correctly over the list it had — *"it's a local renumbered file, so no preset/URL
source applies"* — and inlined 124 KB because nothing else was offered.

## Picking a model

**Binder design** — target in, binder structure + sequence out.

| slug | method | reach for it when |
|---|---|---|
| `rfdiffusion3` | all-atom diffusion, one rollout per design | you want **many cheap backbones**. Reports no confidence — only geometry. Score separately. |
| `bindcraft` | AF2 backpropagation + MPNN redesign + filters | you want sequences worth ordering. Minutes to tens of minutes per trajectory. |
| `boltzdesign` | same, hallucinating through Boltz | a second, independent opinion to BindCraft |
| `proteina` | flow matching + reward search + AF2 refold | generation and validation in one submission |
| `proteinhunter` | predict ⇄ redesign cycles from all-X | **you have only a sequence, no structure**; or you want a cyclic peptide |
| `boltzgen` | all-atom generative | proteins, small-molecule targets, cyclic peptides |

**Two slugs that older notes still name are gone**, both on 2026-09-08.
`pxdesign` was retired upstream. `rfdiffusion` — v1, the RFpeptides macrocycle
entry — was pulled from the catalog because nothing in the fleet can run its
image: its `cu116`/`torch 1.12.1` stack compiles no kernel above sm_86, and the
T4 box it was verified on is gone. `submit_job` and `describe_model` reject both
ids outright, the way they now reject `novafold`. Re-adding v1 is one line in the
registry once the fleet gains a card at or below sm_86, so treat it as a fleet
fact rather than a retirement. Cyclic peptides are still reachable through
`boltzgen` and `proteinhunter`; the RFpeptides path specifically is not.

**Antibodies** — `rfantibody` (VHH/scFv/Fab, framework bundled or uploaded, HLT
format) and `boltzgen` (CDR design onto a framework **you** upload, any
numbering — ANARCI resolves it, measured ~2× faster).

**Structure prediction** — `protenix` for complexes, ligands (CCD codes or
SMILES) and glycans. **ipTM is a prediction of contact, not evidence of
binding** — it says nothing about affinity, expression, solubility, or whether
the thing folds outside the predictor, so never report a design as a binder on
that number alone.

`novaatom` (**NovaAtom** in the UI and on the Models page) is Geodesic
Intelligence's own predictor — a Lite Preview while the full model finishes
training. It was called `novafold`; that id is **gone**, and
`describe_model("novafold")` answers `No model named 'novafold'`. Chains, DNA/RNA and ligands (CCD or SMILES) in;
every diffusion sample out, ranked by its own confidence. Two things to know
before reaching for it. Its **pLDDT is 0–1, not 0–100**: `protenix` uses the
other convention, so the two pLDDT columns are not comparable by eye. And it is
the one entry with **no offline mode at all** — see **Data egress**.

`esmfold` for single chains in seconds, as triage. A low `esmfold` pLDDT means *ask a slower
model*, not *this does not fold*.

**Sequence design** — `proteinmpnn`. Backbone in, sequences out, **no
structures**. Designs the chains you name and conditions on the rest. Weight
sets: vanilla / soluble / CA-only / **AbMPNN** (antibody-finetuned, large
measured effect on antibody backbones).

**Assessment** — `molprobity` (all-atom geometry validation; one structure or a
zip of up to 50; uploads are deliberately *not* sanitized) and `biophi` (antibody
humanness, OASis identity and percentile from 231 human repertoires).

## The pipeline they compose into

```
rfdiffusion3 / bindcraft             →  backbones
        →  proteinmpnn               →  sequences
        →  esmfold (triage) or protenix (accurate)
        →  molprobity (geometry) · biophi (antibody developability)
```

## Traps that cost a job

**Residue numbering is not uniform across models.** Getting this wrong gives a
silently unsteered run, not an error.

- The **uploaded file's own author numbering**: `rfantibody`, `bindcraft`,
  `proteina`, `proteinmpnn`, `rfdiffusion3`, `boltzgen`, `boltzdesign`. The last two
  convert for you: `boltzgen`'s `epitopeNumbering` defaults to `file` — "As uploaded …
  matching every other model in this catalog" — and `boltzdesign` takes `contactResidues`
  "in the uploaded file's own numbering", converting to Boltz's 1-based pocket constraint
  on the platform.
- **1-based ordinals within the chain**: `proteinhunter` alone, and for a reason that does
  not generalise — there is no structure to take numbering from, so its `contactResidues`
  are "counted from 1 along the sequence you pasted". `boltzgen` joins it only if you opt
  in with `epitopeNumbering: ordinal`, which the spec says to choose "only if you counted
  positions from 1 yourself".

**Insertion codes are rejected outright** by `rfdiffusion3` and `proteina`, and
make fixed positions impossible in `proteinmpnn`. This is why uPA (PDB 4DW2,
chymotrypsin-numbered) ships as a preset for most models and not those.

**Most binder models take one chain.** Uploading a complex means picking a
target chain and letting the sanitizer drop everything else — waters, ions,
glycans, altlocs, and any other protein chains. `molprobity` is the exception:
it wants the file whole and unsanitized, because that is what it validates.

**A run returning no passing designs is a normal result** on a hard target,
not a failure. `boltzdesign` is the exception — it crashes rather than reporting
nothing, so "no designs" and "the job failed" are the same event there.

## Data egress

Everything runs locally **except** these, each of which posts your sequences to a
third party. Do not rely on the interface to tell you which: only `proteinhunter` and
`boltzdesign` warn in the field that turns the search on, both in capitals. `protenix`
names its two servers in a picker without calling it egress, and `novaatom` — the one
entry with nothing to turn off — says only that every chain is "searched for homologs
first", naming no destination at all.

- `protenix` in `msa` mode → `protenix-server.com` (the `msaServerMode` default) or
  ColabFold. **This is the default mode.** The live spec's Mode field reads
  `default: "msa"`, and all three shipped presets set `mode: msa`, so a submission that
  does not name a mode egresses. `protenix-v2` would search too, but it ships
  `disabled: true` here — "The Protenix-v2 weights are not available to this deployment"
  — so `msa` is the only protenix mode that can egress at all.

  Its other two modes, `single-sequence` and `fast`, skip the search: the spec shows the
  server picker only for `mode` in `{msa, protenix-v2}`, so neither can reach a server.
  **Neither is a proven escape hatch here.** `single-sequence` is the ESM-based one — the
  spec says a protein language model stands in for the alignment — and it was submitted
  twice on 2026-09-15 and ran out of GPU memory both times, while the same input completed
  in `msa` mode. `fast` ("Lightweight model, no MSA, 4 recycles and 5 diffusion steps") is
  not ESM-based and has no reason to hit that, but nobody has run it on this deployment:
  untested, not cleared. If a sequence must not leave, budget a job to find out.
- `proteinhunter` with `msaMode: mmseqs` → public ColabFold server. Default
  `single` is offline.
- `boltzdesign` with `useMsa: true` → public ColabFold server. Off by default.
- `novaatom` → public ColabFold server, **always**. Its MSA search posts every
  residue of every chain, there is no single-sequence mode, and no field changes
  the server. If a sequence must not leave, this entry is the wrong tool for it.

`proteinhunter` and `boltzdesign` default to offline — leave them there unless the
accuracy is worth the egress. `protenix` has no offline default to leave: its default
searches, and the one offline mode anyone has run here ran out of memory. The trade is
real but smaller than the spec's ladder suggests — on PD-1/PD-L1 the modes move ipTM
0.254 → 0.444, and the 0.900 at the top of that ladder is `protenix-v2`'s, which this
deployment cannot run. `novaatom` has no such choice to offer.

`fetch_artifact` adds no egress: the url it returns points at the platform on the
lab network and the bytes come from there. Treat that url as a credential anyway
— it authorises one file for a couple of minutes with no other authentication, so
it does not belong in anything shared or long-lived.

## What geodesic does not do

Do not reach for a third-party protein API to fill these without saying so
first — they are genuine gaps, not routing problems.

- **No wet lab.** Geodesic is in-silico only. Physical synthesis, BLI/SPR
  binding assays, thermostability and expression titer have **no local
  equivalent** and require an external foundry.
- **ESMFold2 (Full and Fast).** Geodesic's `esmfold` is the *original* ESMFold.
  See `protein-binder-campaign`, where ESMFold2 is two of three mandatory
  ranking arms.
- **ESM3 / ESMC** embeddings and generative design.
- **Docking and MD** — use the local `molecular-dynamics` skill.
- **ipSAE is not a gap in the SCORER.** `ipsae-calculate` computes it locally,
  NumPy only, from any square PAE plus its structure — do not reach for a
  third-party scorer. But see **Getting a result out**: no job here has been
  observed to emit a PAE matrix, so the input usually has to come from
  elsewhere. It implements the stock *pairwise* form; the union-mask variant a
  multimeric target needs is not written.
- Also absent: AlphaFold-Multimer, AlphaFold3/OpenFold3, Chai-1,
  Boltz-1/2 as standalone folders, DockQ, MMseqs2, SolubleCaliby,
  Protpardelle-1c, FoldCraft.
