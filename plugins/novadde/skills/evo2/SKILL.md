---
name: evo2
description: >
  Score, embed, and generate DNA sequences with Evo 2, a long-context genomic
  foundation model. Use this skill when:
  (1) Computing per-nucleotide or per-sequence likelihoods for variant effect
      scoring,
  (2) Embedding genomic windows for downstream classification,
  (3) Generating DNA conditioned on a prefix,
  (4) Scoring regulatory or coding regions across species.
license: Apache-2.0
category: biomodels
requirements: [gpu]
metadata:
  vendored-from: https://github.com/HughYau/AcademicForge (skills/claude-science/evo2)
  vendored-on: "2026-09-03"
  local-changes: "Remote-compute section retargeted to this lab's GPU boxes (geodesic-gpu); model science unchanged."
  display-name: Evo 2
  # github.com/ArcInstitute/evo2/blob/main/LICENSE: Apache-2.0 boilerplate.
  # HuggingFace model cards `arcinstitute/evo2_{40b_base,20b}` declare
  # `license: apache-2.0`. verified 2026-06-30
  third_party:
    - kind: weights
      name: Evo 2
      provider: Arc Institute
      license: Apache-2.0
      terms_url: https://github.com/ArcInstitute/evo2/blob/main/LICENSE
---

# Evo 2 — DNA Language Model

## Prerequisites

| Requirement | Minimum | Recommended      |
| ----------- | ------- | ---------------- |
| Python      | 3.11    | 3.12 (<3.13)     |
| CUDA        | 12.1+   | 12.4+            |
| GPU VRAM    | 24 GB (7B bf16) | 80 GB (40B) |
| RAM         | 32 GB   | 128 GB           |

## How to run

### Installation

```bash
pip install evo2
# Weights pulled from Hugging Face on first model load.
```

### Loading and scoring

```python
from evo2 import Evo2

model = Evo2("evo2_7b")        # or "evo2_40b" — see model table
seqs = ["ATCG" * 50, "GGGCTTAA" * 25]
ll = model.score_sequences(seqs)   # → list[float], mean per-token log-likelihood
print(ll)
```

### Generation

```python
out = model.generate(
    prompt_seqs=["ATGAAAGCT"],
    n_tokens=256,
    temperature=0.7,
)
print(out.sequences[0])
```

## Models

| Name        | Params | Context | VRAM (bf16) | Notes                              |
| ----------- | ------ | ------- | ----------- | ---------------------------------- |
| `evo2_7b`   | 7 B    | 1 M nt  | ~22 GB      | Default; fits on a single 24 GB+ GPU |
| `evo2_40b`  | 40 B   | 1 M nt  | ~78 GB      | H100 80 GB or multi-GPU            |
| `evo2_1b_base` | 1 B | 8 K nt  | ~6 GB       | FP8 path requires sm_89+ (H100)    |

## Output format

`score_sequences` returns a `list[float]` (or `np.ndarray`) of mean log-likelihoods,
one per input sequence. More negative ⇒ less likely under the model. For variant
effect, compute `Δll = ll_alt - ll_ref` over a fixed window.

`generate` returns a `GenerationOutput` with `.sequences` (list[str]), `.logits`
(list[Tensor]), and `.logprobs_mean` (list[float]) — always populated, no flag required.

## Decision tree

```
Need a DNA model?
│
├─ Per-base/per-sequence likelihood, generation → Evo 2 ✓
├─ Predict experimental tracks (expression, accessibility) → borzoi
└─ Protein, not DNA → fair-esm2
```


## Remote compute

These weights are **not in the geodesic registry** — `list_models` does not carry them — so there
is no `submit_job` path and the `geodesic` skill does not apply here. This is the ad-hoc case in
`geodesic-gpu`: launch a box from the Geodesic Compute console, ssh in, build a venv, and run the
script above on it.

| | |
|---|---|
| Card | `l4-*` for the 7B bf16 path — 24 GB is exactly its floor |
| Not T4 | the 7B path is bf16 and T4 is fp16-only, so it errors out rather than running slow |
| 40B | **does not fit this fleet.** It wants 80 GB; the largest card here is a 40 GB A100 |
| Weights | ~15 GB (7B), `arcinstitute/evo2_*` from Hugging Face |
| Egress | the box needs `huggingface.co` on first run |

Cache the weights on the box's own disk and reuse one box across a sweep; a fresh box downloads
them again. Stop or delete the box when the sweep is done — see `geodesic-gpu`.


## Typical performance

| Task                        | 7B on H100 | Notes                       |
| --------------------------- | ---------- | --------------------------- |
| Model load (cached)         | ~5-7 min   | First call hydrates weights |
| `score_sequences`, 200×200bp| ~10-20 s   | After load                  |
| `generate`, 1×512 nt        | ~15 s      |                             |

## Troubleshooting

| Symptom                              | Cause                          | Fix                                        |
| ------------------------------------ | ------------------------------ | ------------------------------------------ |
| `Transformer Engine not installed`   | No FP8 — falls back to bf16    | Informational only on non-H100; ignore     |
| OOM on load                          | 40B on <80 GB GPU              | Use `evo2_7b` or shard with `device_map`   |
| HF tries to write `refs/main`        | `HF_HOME` points at RO mount   | Set `HF_HUB_OFFLINE=1`                     |
| `dtype mismatch` in `score_sequences`| Passing tensors not strings    | Pass `list[str]`; the API tokenises for you |

---

**Next**: pair with `borzoi` to predict track-level effects of the same
variants.
