---
name: fair-esm2
description: >
  Embed proteins with Meta AI's ESM-2 (`fair-esm` package). Use this skill
  when: (1) Extracting per-residue or per-sequence embeddings for downstream
  ML, (2) Masked-LM likelihood / mutation effect scoring, (3) Contact
  prediction from a sequence.
license: Apache-2.0
category: biomodels
requirements: [gpu]
metadata:
  vendored-from: https://github.com/HughYau/AcademicForge (skills/claude-science/fair-esm2)
  vendored-on: "2026-09-03"
  local-changes: "Remote-compute section retargeted to this lab's GPU boxes (geodesic-gpu); model science unchanged."
  display-name: ESM-2
  # github.com/facebookresearch/esm/blob/main/LICENSE: MIT (© Meta Platforms,
  # Inc. and affiliates). verified 2026-06-30
  third_party:
    - kind: weights
      name: ESM-2
      provider: Meta AI
      license: MIT
      terms_url: https://github.com/facebookresearch/esm/blob/main/LICENSE
---

# fair-esm2 — ESM-2 (Meta AI)

ESM-2 code and weights are MIT (Meta AI, github.com/facebookresearch/esm).

> **Package disambiguation.** `pip install fair-esm` gives you `import esm`
> with `esm.pretrained.*` (ESM-1/2). Biohub's github.com/Biohub/esm fork
> (MIT) gives you `from esm.models.esmfold2 import ESMFold2InputBuilder` —
> see the **`esmfold2`** skill. Both share the `esm` namespace but are
> different libraries. This skill covers **fair-esm** (the Meta package).

## Prerequisites

| Requirement | Minimum | Recommended |
| ----------- | ------- | ----------- |
| Python      | 3.8+    | 3.11        |
| CUDA        | 11.7+   | 12.x        |
| GPU VRAM    | 8 GB (8M), 16 GB (650M) | 24 GB+ (650M / 3B) |

## How to run

### Embeddings

```python
import torch, esm

model, alphabet = esm.pretrained.esm2_t33_650M_UR50D()
model = model.eval().cuda()
bc = alphabet.get_batch_converter()

_, _, toks = bc([("ubq", "MQIFVKTLTGKTITLEVEPSDTIENVK")])
with torch.no_grad():
    out = model(toks.cuda(), repr_layers=[33])
emb = out["representations"][33]      # (1, L+2, 1280) — includes BOS/EOS
seq_emb = emb[0, 1:-1].mean(0)        # per-sequence mean
```

### Masked-LM scoring

**Two different computations.** `plm-variant-scoring` owns which to use and what each costs;
this is how to produce them. They yield identically shaped tables, so nothing downstream can
tell them apart — label whichever you compute.

**wt-marginal** — one forward pass, nothing masked:

```python
import torch.nn.functional as F

with torch.no_grad():
    out = model(toks.cuda(), repr_layers=[33])
# log_softmax over the vocabulary, not raw logits. The difference cancels for a single
# substitution and does not for anything summed over positions.
lp = F.log_softmax(out["logits"][0], dim=-1)     # (L+2, |vocab|); BOS is index 0
score = lp[1 + pos, alphabet.get_idx(mut)] - lp[1 + pos, alphabet.get_idx(wt)]
```

**masked-marginal** — L forward passes, position `i` masked in pass `i`. It is a separate
loop, not a comment on the one above:

```python
table = torch.empty(len(seq), len(alphabet))
for i in range(len(seq)):
    masked = toks.clone()
    masked[0, 1 + i] = alphabet.mask_idx
    with torch.no_grad():
        table[i] = F.log_softmax(model(masked.cuda())["logits"][0, 1 + i], dim=-1)
```

`1 + pos` throughout because the alphabet prepends BOS. Higher score means the model finds
the mutant **more** likely.

### Contact prediction

```python
with torch.no_grad():
    out = model(toks.cuda(), repr_layers=[33], return_contacts=True)
contacts = out["contacts"][0]         # (L, L)
```

## Models

| Name                       | Layers | Dim  | Params | Use                        |
| -------------------------- | ------ | ---- | ------ | -------------------------- |
| `esm2_t6_8M_UR50D`         | 6      | 320  | 8 M    | Fast smoke / tiny embeddings |
| `esm2_t33_650M_UR50D`      | 33     | 1280 | 650 M  | Default embedding model    |
| `esm2_t36_3B_UR50D`        | 36     | 2560 | 3 B    | Best embeddings, 24 GB+    |

## Output format

`out["representations"][layer]` is `(B, L+2, D)`; slice `[ :, 1:-1, : ]` to
drop BOS/EOS. `out["contacts"]` (when `return_contacts=True`) is `(B, L, L)`.


## Remote compute

These weights are **not in the geodesic registry** — `list_models` does not carry them — so there
is no `submit_job` path and the `geodesic` skill does not apply here. This is the ad-hoc case in
`geodesic-gpu`: launch a box from the Geodesic Compute console, ssh in, build a venv, and run the
script above on it.

| | |
|---|---|
| Card | `l4-*` for 650M/3B; `t4-*` carries the 8M and the fp16 650M path, but not bf16 |
| Weights | via `torch.hub`; set `TORCH_HOME` to a path on the box's own disk |
| Egress | the box needs `dl.fbaipublicfiles.com` on first run |

Cache the weights on the box's own disk and reuse one box across a sweep; a fresh box downloads
them again. Stop or delete the box when the sweep is done — see `geodesic-gpu`.


## Troubleshooting

| Symptom                                       | Cause                              | Fix                                   |
| --------------------------------------------- | ---------------------------------- | ------------------------------------- |
| `ModuleNotFoundError: No module named 'esm.models'` | You want Biohub's `esm` fork, not `fair-esm` | This skill uses `esm.pretrained.*`; the Biohub fork is not packaged here |
| Slow first call                               | Downloading weights via torch.hub  | Set `TORCH_HOME` to a cached location |

---

**Next**: feed embeddings to a classifier. For structure prediction, use
`esmfold2`.
