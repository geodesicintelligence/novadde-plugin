---
name: borzoi
description: >
  Predict genome-wide functional tracks (RNA-seq, CAGE, DNase, ChIP) from DNA
  sequence with Borzoi. Use this skill when:
  (1) Scoring the regulatory effect of a variant on expression/accessibility,
  (2) Generating predicted coverage tracks for a locus,
  (3) Prioritising non-coding variants by predicted track delta.
license: Apache-2.0
category: biomodels
requirements: [gpu]
metadata:
  vendored-from: https://github.com/HughYau/AcademicForge (skills/claude-science/borzoi)
  vendored-on: "2026-09-03"
  local-changes: "Remote-compute section retargeted to this lab's GPU boxes (geodesic-gpu); model science unchanged."
  # SKILL.md loads `johahi/borzoi-replicate-0` — a PyTorch port of Calico's
  # Borzoi ("ported weights (with permission)"). The HuggingFace model card
  # for that exact artifact states `License: cc-by-4.0`. Calico's CODE repo is
  # Apache-2.0, but the weights the skill downloads carry CC-BY-4.0. The model
  # card is where the license is declared (info_url — not a ToU page).
  # verified 2026-06-30
  third_party:
    - kind: weights
      name: Borzoi (PyTorch port)
      provider: Calico Life Sciences
      license: CC-BY-4.0
      info_url: https://huggingface.co/johahi/borzoi-replicate-0
---

# Borzoi — DNA → Functional Track Prediction

## Prerequisites

| Requirement | Minimum | Recommended |
| ----------- | ------- | ----------- |
| Python      | 3.10+   | 3.11        |
| CUDA        | 12.1+   | 12.4+       |
| GPU VRAM    | 16 GB   | 24 GB+      |

## How to run

```python
from borzoi_pytorch import Borzoi

model = Borzoi.from_pretrained("johahi/borzoi-replicate-0").cuda().eval()
# input: (batch, 4, 524288) one-hot DNA  → output: (batch, tracks, 6144) bins
```

Borzoi consumes ~524 kb one-hot windows and emits binned predictions across
7,611 human tracks (the separate 2,608-track mouse head is off by default;
enable via `enable_mouse_head=True` and select with
`forward(..., is_human=False)`). For variant scoring, run ref/alt windows
centred on the variant and compare per-track output.

## Output format

`(B, T, L)` tensor — `T` tracks × `L` 32-bp bins. Track metadata (assay,
biosample) is in `borzoi_pytorch.pytorch_borzoi_model.TRACKS_DF` (or `model.tracks_df` when using the `AnnotatedBorzoi` subclass) — the base `Borzoi` model has no `targets` attribute.


## Remote compute

These weights are **not in the geodesic registry** — `list_models` does not carry them — so there
is no `submit_job` path and the `geodesic` skill does not apply here. This is the ad-hoc case in
`geodesic-gpu`: launch a box from the Geodesic Compute console, ssh in, build a venv, and run the
script above on it.

| | |
|---|---|
| Card | `l4-*` (24 GB recommended, 16 GB is the floor) |
| Weights | `johahi/borzoi-replicate-0` from Hugging Face |
| Egress | the box needs `huggingface.co` on first run |

Cache the weights on the box's own disk and reuse one box across a sweep; a fresh box downloads
them again. Stop or delete the box when the sweep is done — see `geodesic-gpu`.


## Troubleshooting

| Symptom                        | Cause                    | Fix                                  |
| ------------------------------ | ------------------------ | ------------------------------------ |
| `module has no __version__`    | Package exposes no attr  | Use `importlib.metadata.version("borzoi-pytorch")` |
| Shape mismatch on input        | Wrong window length      | Pad/crop to 524288 bp (fixed; not exposed as a model attribute) |

---

**Next**: combine track deltas with `evo2` likelihood deltas for a
two-axis variant prioritisation.
