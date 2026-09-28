#!/usr/bin/env python3
"""Does the binder hold its fold when the target is taken away?

A design can score well in complex and be disordered on its own. That is a real failure --
the target is doing the folding -- and it is ORTHOGONAL to interface confidence: a design
with good ipTM and a collapsing apo fold passes every interface gate there is.

So fold the binder twice: once in complex (holo) and once alone (apo), then superpose the
binder's own CA atoms and measure. Low RMSD means pre-organised. High RMSD means the fold
depends on the partner, which is a weaker design and a harder one to make work.

What this computes, and nothing more: the CA RMSD of one chain between two structures, by
Kabsch superposition, with the residue correspondence checked rather than assumed.

The thresholds are NOT calibrated -- see the skill. This prints the number and, only if you
name a cutoff, whether it is under it.

Stdlib + numpy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


class InputError(RuntimeError):
    """Something about the inputs is wrong in a way guessing would not fix."""


def _cif_ca(text: str, chains: set[str]) -> dict[str, np.ndarray]:
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip().startswith("_atom_site.")), None)
    if start is None:
        raise InputError("mmCIF has no _atom_site loop")
    cols, i = [], start
    while i < len(lines) and lines[i].strip().startswith("_atom_site."):
        cols.append(lines[i].strip().split(".", 1)[1])
        i += 1
    need = {"label_atom_id", "label_asym_id", "label_seq_id", "Cartn_x", "Cartn_y", "Cartn_z"}
    if need - set(cols):
        raise InputError(f"mmCIF _atom_site missing {sorted(need - set(cols))}")
    ch_key = "auth_asym_id" if "auth_asym_id" in cols else "label_asym_id"
    id_key = "auth_seq_id" if "auth_seq_id" in cols else "label_seq_id"
    out: dict[str, dict] = {}
    for ln in lines[i:]:
        s = ln.strip()
        if not s or s.startswith(("#", "loop_", "_", "data_")):
            break
        f = s.split()
        if len(f) < len(cols):
            continue
        row = dict(zip(cols, f))
        if row["label_atom_id"] != "CA":
            continue
        if chains and row[ch_key] not in chains:
            continue
        b = float(row.get("B_iso_or_equiv", "nan") or "nan")
        out.setdefault(row[ch_key], {})[row[id_key]] = (
            float(row["Cartn_x"]), float(row["Cartn_y"]), float(row["Cartn_z"]), b)
    return {c: v for c, v in out.items()}


def _pdb_ca(text: str, chains: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ln in text.splitlines():
        if not ln.startswith(("ATOM  ", "HETATM")) or ln[12:16].strip() != "CA":
            continue
        ch = ln[21:22].strip() or "A"
        if chains and ch not in chains:
            continue
        try:
            b = float(ln[60:66])
        except ValueError:
            b = float("nan")
        out.setdefault(ch, {})[ln[22:27].strip()] = (
            float(ln[30:38]), float(ln[38:46]), float(ln[46:54]), b)
    return out


def load_ca(path: Path, chains: set[str]) -> dict[str, dict]:
    """CA coordinates per chain, keyed by residue id so two files can be matched by
    identity rather than by position -- a holo file with an extra target chain, or a
    renumbered apo model, must not silently pair the wrong residues."""
    if not path.is_file():
        raise InputError(f"{path}: no such file")
    text = path.read_text()
    got = (_cif_ca(text, chains) if path.suffix.lower() in (".cif", ".mmcif")
           else _pdb_ca(text, chains))
    if not got:
        named = f" for chain(s) {sorted(chains)}" if chains else ""
        raise InputError(f"{path.name}: no CA atoms found{named}")
    return got


def kabsch_rmsd(p: np.ndarray, q: np.ndarray) -> float:
    """RMSD after optimal superposition. Translation and rotation removed; no scaling.

    Reflection is explicitly excluded -- the determinant correction below. Without it a
    mirror image can superpose "better" than the real thing and report a flattering RMSD
    for a structure that is not the same structure.
    """
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3:
        raise InputError(f"cannot superpose shapes {p.shape} and {q.shape}")
    pc, qc = p - p.mean(axis=0), q - q.mean(axis=0)
    u, s, vt = np.linalg.svd(pc.T @ qc)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    diff = (rot @ pc.T).T - qc
    return float(np.sqrt((diff ** 2).sum() / len(p)))


def confidence(ca: dict, chains: list[str]) -> dict:
    """Summarise the B-factor column of a PREDICTED model, where folders write pLDDT.

    Two traps, both silent, both encoded here rather than guessed around:

    1. Scale. Some writers put pLDDT in 0-100, others in 0-1. A 0.70 cutoff applied to a
       0-100 file passes everything; applied the other way it fails everything. The scale
       is detected from the values and REPORTED, never assumed.
    2. Provenance. In an EXPERIMENTAL structure this same column is the crystallographic
       B-factor, where low is good -- the opposite direction. Nothing in the file says
       which it is, so this is opt-in (--plddt) and the report says what was assumed.
    """
    vals = [b for c in chains for b in (v[3] for v in ca[c].values())
            if b == b]  # NaN != NaN drops unparsable rows
    if not vals:
        raise InputError("no B-factor/pLDDT column values found; cannot report confidence")
    hi = max(vals)
    if hi > 1.5:
        scale, norm = "0-100", [v / 100.0 for v in vals]
    else:
        scale, norm = "0-1", list(vals)
    mean = sum(norm) / len(norm)
    return {
        "mean_plddt": round(mean, 4),
        "min_plddt": round(min(norm), 4),
        "fraction_below_0.70": round(sum(1 for v in norm if v < 0.70) / len(norm), 4),
        "detected_scale": scale,
        "reported_on": "0-1",
        "assumed": ("the B-factor column holds pLDDT, i.e. this is a predicted model. "
                    "For an experimental structure it is a crystallographic B-factor and "
                    "means the opposite -- do not read these numbers as confidence."),
    }


def compare(apo: Path, holo: Path, binder_chains: list[str], cutoff: float | None,
            plddt: bool = False) -> dict:
    wanted = set(binder_chains)
    a, h = load_ca(apo, wanted), load_ca(holo, wanted)
    shared_chains = sorted(set(a) & set(h))
    if not shared_chains:
        raise InputError(
            f"no binder chain is in both files: apo has {sorted(a)}, holo has {sorted(h)}. "
            "Name the binder chain as it appears in each, with --binder-chains."
        )

    pa, ph, per_chain = [], [], {}
    for c in shared_chains:
        common = [r for r in a[c] if r in h[c]]
        only_apo = sorted(set(a[c]) - set(h[c]))
        only_holo = sorted(set(h[c]) - set(a[c]))
        if not common:
            raise InputError(
                f"chain {c}: no residue id appears in both files. The apo model is probably "
                "renumbered; matching by position instead would pair the wrong residues."
            )
        common.sort(key=lambda r: (len(r), r))
        pa.extend(a[c][r][:3] for r in common)
        ph.extend(h[c][r][:3] for r in common)
        per_chain[c] = {"matched_residues": len(common),
                        "only_in_apo": len(only_apo), "only_in_holo": len(only_holo)}

    rmsd = kabsch_rmsd(np.asarray(pa), np.asarray(ph))
    out = {
        "apo_holo_ca_rmsd": round(rmsd, 4),
        "binder_chains": shared_chains,
        "per_chain": per_chain,
        "superposition": "Kabsch, CA only, reflection excluded",
        "means": ("low = the binder is pre-organised and holds its fold alone; "
                  "high = the fold depends on the target, which is a weaker design"),
    }
    dropped = sum(v["only_in_apo"] + v["only_in_holo"] for v in per_chain.values())
    if dropped:
        out["unmatched_residues"] = dropped
        out["note"] = (f"{dropped} residues appear in only one file and were excluded. An RMSD "
                       "over a subset is not comparable with one over the whole chain.")
    if plddt:
        out["apo_confidence"] = confidence(a, shared_chains)
    if cutoff is not None:
        out["cutoff"] = cutoff
        out["under_cutoff"] = rmsd <= cutoff
        out["cutoff_provenance"] = "yours -- this script ships no default, see the skill"
    return out


def _selftest() -> int:
    ok = True

    def check(label, got, want, tol=1e-6):
        nonlocal ok
        good = abs(got - want) < tol if isinstance(want, float) else got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    rng = np.random.default_rng(0)
    x = rng.normal(size=(30, 3)) * 10

    print("Kabsch, against answers known in advance")
    check("a structure against itself is 0", round(kabsch_rmsd(x, x), 9), 0.0)
    check("translation is removed", round(kabsch_rmsd(x, x + [5.0, -3.0, 2.0]), 9), 0.0)
    theta = 0.7
    rot = np.array([[np.cos(theta), -np.sin(theta), 0],
                    [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])
    check("rotation is removed", round(kabsch_rmsd(x, (rot @ x.T).T), 9), 0.0)
    check("rotation AND translation", round(kabsch_rmsd(x, (rot @ x.T).T + [1, 2, 3]), 9), 0.0)
    # A mirror image is NOT the same structure; excluding reflection is what says so.
    check("a reflection is not superposable to zero",
          kabsch_rmsd(x, x * [1, 1, -1]) > 1.0, True)
    # Displace one atom by d. Two closed forms bracket the answer, and the gap between
    # them is the point: d/sqrt(N) is what you get with no superposition at all;
    # d*sqrt(N-1)/N is what remains after the centroid shift is removed; the true
    # optimum is at or below that because rotation can absorb a little more. A Kabsch
    # that landed ON the naive value would be doing no superposition.
    y = x.copy(); y[0] += [3.0, 0.0, 0.0]
    got = kabsch_rmsd(x, y)
    n = len(x)
    check("below the no-superposition value", got < 3.0 / np.sqrt(n), True)
    check("at or below the centering-only value", got <= 3.0 * np.sqrt(n - 1) / n, True)
    check("and within 1% of it (rotation absorbs little here)",
          abs(got - 3.0 * np.sqrt(n - 1) / n) < 0.01 * got, True)
    check("scaling is NOT removed", kabsch_rmsd(x, x * 1.5) > 1.0, True)

    print("residues are matched by id, not by position")
    import tempfile  # noqa: PLC0415
    tmp = Path(tempfile.mkdtemp())

    def pdb(path, ids, coords, chain="A"):
        rows = []
        for n, (i, c) in enumerate(zip(ids, coords), start=1):
            rows.append(f"ATOM  {n:5d}  CA  ALA {chain}{i:4d}    "
                        f"{c[0]:8.3f}{c[1]:8.3f}{c[2]:8.3f}  1.00  0.00           C")
        (tmp / path).write_text("\n".join(rows) + "\nEND\n")
        return tmp / path

    coords = [(float(i), 0.0, 0.0) for i in range(10)]
    apo = pdb("apo.pdb", range(1, 11), coords)
    holo = pdb("holo.pdb", range(1, 11), coords)
    r = compare(apo, holo, ["A"], None)
    check("identical files give 0", r["apo_holo_ca_rmsd"], 0.0)
    check("all ten matched", r["per_chain"]["A"]["matched_residues"], 10)

    # holo carries a target chain the apo does not: must not be compared
    holo2 = tmp / "holo2.pdb"
    holo2.write_text((tmp / "holo.pdb").read_text().replace("END\n", "") +
                     "\n".join(f"ATOM  {900+n:5d}  CA  ALA B{n:4d}    "
                               f"{50.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C"
                               for n in range(1, 6)) + "\nEND\n")
    r2 = compare(apo, holo2, ["A"], None)
    check("the target chain is not dragged in", r2["binder_chains"], ["A"])
    check("and the RMSD is unchanged", r2["apo_holo_ca_rmsd"], 0.0)

    # a renumbered apo shares no residue id: refuse rather than pair by position
    shifted = pdb("shift.pdb", range(101, 111), coords)
    try:
        compare(shifted, holo, ["A"], None)
    except InputError as exc:
        check("a renumbered apo is refused", "renumbered" in str(exc), True)
    else:
        check("a renumbered apo is refused", "no refusal", "InputError")

    # partial overlap is used but declared
    part = pdb("part.pdb", range(1, 8), coords[:7])
    r3 = compare(part, holo, ["A"], None)
    check("only the shared residues are compared", r3["per_chain"]["A"]["matched_residues"], 7)
    check("and the exclusion is reported", r3["unmatched_residues"], 3)

    print("the pLDDT scale is detected, not assumed")

    def pdb_b(path, bvals):
        rows = [f"ATOM  {n:5d}  CA  ALA A{n:4d}    "
                f"{float(n):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00{b:6.2f}           C"
                for n, b in enumerate(bvals, start=1)]
        (tmp / path).write_text("\n".join(rows) + "\nEND\n")
        return tmp / path

    # 70.0 sits EXACTLY on the gate. Without it, `< 0.70` and `<= 0.70` agree on every
    # fixture and the boundary is untested -- which is how a flipped comparison survives.
    hundred = pdb_b("b100.pdb", [95.0, 80.0, 70.0, 60.0, 40.0])
    c = confidence(load_ca(hundred, {"A"}), ["A"])
    check("0-100 input is detected", c["detected_scale"], "0-100")
    check("and normalised to 0-1", c["mean_plddt"], round((0.95+0.80+0.70+0.60+0.40)/5, 4))
    check("exactly 0.70 is NOT below 0.70", c["fraction_below_0.70"], 0.4)

    unit = pdb_b("b1.pdb", [0.95, 0.80, 0.70, 0.60, 0.40])
    c2 = confidence(load_ca(unit, {"A"}), ["A"])
    check("0-1 input is detected", c2["detected_scale"], "0-1")
    check("and gives the SAME answer as the 0-100 file", c2["mean_plddt"], c["mean_plddt"])
    check("a 0-100 file is not silently compared to 0.70",
          c["mean_plddt"] < 1.0, True)
    check("the B-factor ambiguity is stated", "experimental" in c["assumed"], True)

    print("confidence is opt-in, because the column may not be pLDDT at all")
    check("absent by default", "apo_confidence" in compare(apo, holo, ["A"], None), False)
    check("present when asked", "apo_confidence" in compare(apo, holo, ["A"], None, plddt=True), True)

    print("no default cutoff is invented")
    check("absent unless asked", "cutoff" in compare(apo, holo, ["A"], None), False)
    r4 = compare(apo, holo, ["A"], 2.5)
    check("present when asked", r4["under_cutoff"], True)
    # apo vs holo here is exactly 0.0, so a cutoff of 0.0 lands ON the boundary.
    check("a cutoff equal to the RMSD passes (inclusive)",
          compare(apo, holo, ["A"], 0.0)["under_cutoff"], True)
    y = pdb("far.pdb", range(1, 11), [(float(i) * 1.5, 0.0, 0.0) for i in range(10)])
    check("and a real difference fails it",
          compare(y, holo, ["A"], 0.0)["under_cutoff"], False)
    check("and attributed to you", "yours" in r4["cutoff_provenance"], True)

    print("\n" + ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--apo", type=Path, help="the binder folded alone")
    p.add_argument("--holo", type=Path, help="the binder folded with its target")
    p.add_argument("--binder-chains", default="", help="comma-separated, e.g. A")
    p.add_argument("--cutoff", type=float, help="RMSD you consider acceptable; none by default")
    p.add_argument("--plddt", action="store_true",
                   help="also summarise the apo B-factor column as pLDDT (predicted models only)")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        return _selftest()
    if not args.apo or not args.holo:
        p.error("--apo and --holo are both required (or use --selftest)")
    try:
        report = compare(args.apo, args.holo,
                         [c for c in args.binder_chains.split(",") if c], args.cutoff,
                         plddt=args.plddt)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
