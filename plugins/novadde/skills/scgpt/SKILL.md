---
name: scgpt
description: >
  Embed and annotate single-cell expression data with scGPT, a foundation model
  for single-cell biology. Use this skill when:
  (1) Producing cell embeddings from an AnnData for clustering/integration,
  (2) Zero-shot or fine-tuned cell-type annotation,
  (3) Gene-level representation for perturbation/GRN tasks.

  For probabilistic single-cell models (scVI etc.), use the scvi-tools
  library.
license: Apache-2.0
category: biomodels
requirements: [gpu]
metadata:
  vendored-from: https://github.com/HughYau/AcademicForge (skills/claude-science/scgpt)
  vendored-on: "2026-09-03"
  local-changes: "Remote-compute section retargeted to this lab's GPU boxes (geodesic-gpu); model science unchanged."
  display-name: scGPT
  # scGPT checkpoints are distributed as unlabeled Google Drive directories
  # (linked from github.com/bowang-lab/scGPT); the repo LICENSE (MIT) covers
  # the CODE, and no source states a weights license. Per the sourcing rule:
  # leave `license` absent. Repo root is a README, not a terms page —
  # info_url. verified 2026-06-30
  third_party:
    - kind: weights
      name: scGPT
      provider: Wang Lab (University of Toronto)
      info_url: https://github.com/bowang-lab/scGPT
---

# scGPT — Single-Cell Foundation Model

## Prerequisites

| Requirement | Minimum | Recommended |
| ----------- | ------- | ----------- |
| Python      | 3.10+   | 3.11        |
| CUDA        | 12.1+   | 12.4+       |
| GPU VRAM    | 16 GB   | 24 GB+      |

## How to run

### Loading the vocabulary and checkpoint

scGPT checkpoints are **raw directories** (`args.json`, `best_model.pt`,
`vocab.json`) — not Hugging Face hub repos. Point at the directory, not an HF
repo id.

```python
from scgpt.tokenizer.gene_tokenizer import GeneVocab
gv = GeneVocab.from_file("/path/to/scgpt-human/vocab.json")
print(len(gv))   # 60697 for the released human checkpoint
```

### Embedding an AnnData

```python
import anndata as ad
from scgpt.tasks import embed_data

adata = ad.read_h5ad("dataset.h5ad")        # var must contain a gene-name column
emb = embed_data(
    adata,
    model_dir="/path/to/scgpt-human",
    gene_col="feature_name",
    use_fast_transformer=False,             # see Gotchas
)
# emb is an AnnData with .obsm["X_scGPT"]
```

## Output format

`embed_data` returns an `AnnData` whose `.obsm["X_scGPT"]` is the per-cell
embedding (`n_cells × emb_dim`, 512 by default). Downstream: feed to
`scanpy.pp.neighbors` / `scanpy.tl.umap`.


## Remote compute

These weights are **not in the geodesic registry** — `list_models` does not carry them — so there
is no `submit_job` path and the `geodesic` skill does not apply here. This is the ad-hoc case in
`geodesic-gpu`: launch a box from the Geodesic Compute console, ssh in, build a venv, and run the
script above on it.

| | |
|---|---|
| Card | `l4-*` (24 GB recommended, 16 GB is the floor) |
| Weights | the released human checkpoint, ~200 MB, distributed as an unlabeled Google Drive directory |
| Egress | none once the checkpoint is on the box — fetch it yourself and copy it up |

Cache the weights on the box's own disk and reuse one box across a sweep; a fresh box downloads
them again. Stop or delete the box when the sweep is done — see `geodesic-gpu`.


## Gotchas

- **`use_fast_transformer` default is `True`** but resolves to a FlashAttention
  path that may not import in every env. Pass `use_fast_transformer=False`
  unless you've confirmed `flash_attn` loads cleanly.
- The package historically depended on `torchtext.vocab.Vocab`; in
  environments without torchtext a pure-Python shim provides `Vocab` —
  functionally identical for `GeneVocab`, but if you hit
  `AttributeError: 'Vocab' object has no attribute …`, you're on a stale shim.
- Gene names must match the vocab; unmatched genes are dropped. Set
  `gene_col` to the column in `adata.var` that holds symbols.

## Troubleshooting

| Symptom                                           | Fix                                              |
| ------------------------------------------------- | ------------------------------------------------ |
| `flash_attn is not installed` warning at import   | Harmless; pass `use_fast_transformer=False`      |
| `'Vocab' object has no attribute 'vocab'`         | Env has an old torchtext shim — update the env   |
| Nearly all genes dropped                          | Wrong `gene_col`; check `adata.var.columns`      |
| "scgpt not in manifest" / env-detection misses scGPT | The baked env manifest lists the distribution as `scGPT` (and `flash_attn`), pip's canonical casing — normalize manifest keys before lookup: `name.lower().replace('-', '_')` |

---

**Next**: cluster/annotate the embedding with the scanpy library
(`sc.pp.neighbors` → `sc.tl.leiden` / `sc.tl.umap`), or compare to an
scvi-tools latent space on the same data.
