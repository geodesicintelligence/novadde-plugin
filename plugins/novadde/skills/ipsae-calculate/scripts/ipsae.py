#!/usr/bin/env python3
"""ipSAE and contact-interface PAE for a predicted complex, per chain pair.

ipSAE follows Dunbrack, "Res ipSAE loquuntur" (doi:10.1101/2025.02.10.637595), formulas
14-16. This is an independent implementation of the protein formulas, not a copy of the
author's program, and it does not reproduce the nucleic-acid extension or the auxiliary
ipSAE_d0chn / ipSAE_d0dom variants.

Four decisions in here exist because the obvious alternative is wrong:

* **Never a bare maximum over every chain pair.** ipSAE is defined per ordered pair.
  Reducing a complex to one number by maxing over all of them returns, for a paired
  VH/VL binder against an antigen, the VH-VL interface -- conserved, well packed, and
  predicted far better than any designed paratope. Pass --binder-chains/--target-chains
  and the headline number is the best interface that CROSSES that boundary; without
  them every pair is reported and no headline number is invented.

* **Zero is not one fact.** No residue pair cleared the PAE cutoff, the chains are not in
  contact at all, and the calculation failed are three different outcomes. Each carries
  its own status, and a failure exits non-zero instead of printing a score.

* **The PAE cutoff never touches iPAE.** Dropping high-PAE pairs before averaging them
  flatters the average. Contact selection is geometric; the cutoff is for ipSAE only.

* **PAE is asymmetric and stays that way.** Both directions are computed and reported
  separately; nothing is symmetrised, averaged, or min-ed before the score.

Input it accepts, and refuses everything else rather than guessing:
  PAE        JSON carrying exactly one of pae / predicted_aligned_error / pae_matrix,
             or an .npz carrying one of those keys.
  structure  mmCIF (_atom_site loop) or PDB ATOM/HETATM records.
Rows/columns of the PAE must correspond 1:1 with the structure's protein residues, in
order. When they do not the run stops and says by how much; a silent truncation here
produces a confident score for a different molecule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

# Formula 15. Below the boundary d0 is 1 A exactly -- not the cube root evaluated at 27,
# which is 1.0389 and scores every small interface a few percent high.
D0_MIN_LENGTH = 27
_PAE_KEYS = ("pae", "predicted_aligned_error", "pae_matrix")
_ELEMENTS_TO_DROP = {"H", "D", "T"}


class InputError(RuntimeError):
    """Something about the inputs is wrong in a way guessing would not fix."""


def require_file(label: str, path: Path) -> Path:
    """Fail the way every other bad input fails. A mistyped path is the most common
    error there is, and answering it with a pathlib traceback tells the user nothing
    about which of the two arguments they got wrong."""
    if not path.exists():
        raise InputError(f"{label} {path}: no such file")
    if not path.is_file():
        raise InputError(f"{label} {path}: not a file")
    return path


def d0(length: int) -> float:
    """Formula 15, evaluated per aligned residue from that row's qualifying count."""
    if length < D0_MIN_LENGTH:
        return 1.0
    return 1.24 * (length - 15) ** (1.0 / 3.0) - 1.8


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- inputs ------------------------------------------------------------------


def load_pae(path: Path) -> np.ndarray:
    if path.suffix == ".npz":
        with np.load(path) as handle:
            present = [k for k in _PAE_KEYS if k in handle]
            if len(present) != 1:
                raise InputError(
                    f"{path.name}: expected exactly one of {list(_PAE_KEYS)}, found {present}"
                )
            matrix = np.asarray(handle[present[0]], dtype=float)
    else:
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise InputError(f"{path.name}: not valid JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise InputError(f"{path.name}: expected a JSON object")
        present = [k for k in _PAE_KEYS if k in data]
        if len(present) != 1:
            raise InputError(
                f"{path.name}: expected exactly one of {list(_PAE_KEYS)}, found {present}. "
                "A summary_confidences file carries no PAE."
            )
        matrix = np.asarray(data[present[0]], dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise InputError(f"{path.name}: PAE must be square, got shape {matrix.shape}")
    return matrix


def _cif_atoms(text: str) -> list[dict]:
    """Rows of the _atom_site loop, as dicts keyed by column name."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith("_atom_site.")]
    if not starts:
        raise InputError("mmCIF has no _atom_site loop")
    columns: list[str] = []
    index = starts[0]
    while index < len(lines) and lines[index].strip().startswith("_atom_site."):
        columns.append(lines[index].strip().split(".", 1)[1])
        index += 1
    needed = {"label_atom_id", "label_asym_id", "label_seq_id",
              "Cartn_x", "Cartn_y", "Cartn_z", "type_symbol"}
    missing = needed - set(columns)
    if missing:
        raise InputError(f"mmCIF _atom_site is missing {sorted(missing)}")
    rows = []
    for line in lines[index:]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "loop_", "_", "data_")):
            break
        fields = stripped.split()
        if len(fields) < len(columns):
            continue
        rows.append(dict(zip(columns, fields)))
    if not rows:
        raise InputError("mmCIF _atom_site loop has no rows")
    return rows


def _pdb_atoms(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        rows.append(
            {
                "label_atom_id": line[12:16].strip(),
                "label_asym_id": line[21:22].strip() or "A",
                # 23-26 plus the insertion code in 27, so 100 and 100A stay distinct.
                "label_seq_id": line[22:27].strip(),
                "Cartn_x": line[30:38],
                "Cartn_y": line[38:46],
                "Cartn_z": line[46:54],
                # Columns 77-78. Falling back to the atom name's first letter is wrong for
                # two-letter elements but right for the hydrogens this is used to screen.
                "type_symbol": line[76:78].strip() or line[12:16].strip()[:1],
            }
        )
    if not rows:
        raise InputError("PDB has no ATOM/HETATM records")
    return rows


def load_residues(path: Path) -> list[dict]:
    """Protein residues in file order: chain, id, and heavy-atom coordinates.

    A residue is kept when it has a CA. That drops waters, ions and most ligands without
    having to name them, which is what the PAE's protein rows correspond to.

    Chain and residue labels come from the auth_* columns when the file has them, because
    those are the identifiers the user sees in PyMOL and types on the command line.
    """
    text = path.read_text()
    is_cif = path.suffix.lower() in (".cif", ".mmcif")
    rows = _cif_atoms(text) if is_cif else _pdb_atoms(text)
    chain_key = "auth_asym_id" if "auth_asym_id" in rows[0] else "label_asym_id"
    resid_key = "auth_seq_id" if "auth_seq_id" in rows[0] else "label_seq_id"

    order: list[tuple[str, str]] = []
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row[chain_key], row[resid_key])
        if key not in grouped:
            grouped[key] = {"chain": key[0], "resid": key[1], "coords": [], "has_ca": False}
            order.append(key)
        entry = grouped[key]
        if row["label_atom_id"] == "CA":
            entry["has_ca"] = True
        if row["type_symbol"].upper() in _ELEMENTS_TO_DROP:
            continue
        try:
            entry["coords"].append(
                (float(row["Cartn_x"]), float(row["Cartn_y"]), float(row["Cartn_z"]))
            )
        except ValueError as exc:
            raise InputError(f"unparseable coordinate in {path.name}: {exc}") from exc

    residues = [grouped[k] for k in order if grouped[k]["has_ca"] and grouped[k]["coords"]]
    if not residues:
        raise InputError(f"{path.name}: no protein residues with a CA and heavy atoms")
    for entry in residues:
        entry["xyz"] = np.asarray(entry["coords"], dtype=float)
        del entry["coords"]
    return residues


# -- the score ---------------------------------------------------------------


def ipsae_directional(pae: np.ndarray, rows: np.ndarray, cols: np.ndarray,
                      cutoff: float) -> dict:
    """ipSAE(A->B): mean over each row's qualifying partners, then the max over rows.

    `rows` index the aligned chain, `cols` the scored one, both into the full PAE. The
    matrix is read as given -- row i is the aligned residue, column j the scored one.
    """
    block = pae[np.ix_(rows, cols)]
    qualifying = block < cutoff           # strictly less than, per the paper
    counts = qualifying.sum(axis=1)
    scores = np.zeros(block.shape[0], dtype=float)
    for i in range(block.shape[0]):
        if counts[i] == 0:
            continue                      # a row with no partner scores 0, not NaN
        values = block[i][qualifying[i]]
        scale = d0(int(counts[i]))
        scores[i] = float(np.mean(1.0 / (1.0 + (values / scale) ** 2)))
    per_residue = [round(float(s), 6) for s in scores]
    if not scores.size or not scores.any():
        return {"score": 0.0, "anchor": None, "n0res": 0, "d0": None,
                "status": "no_qualifying_pairs", "per_residue": per_residue}
    best = int(np.argmax(scores))
    return {
        "score": float(scores[best]),
        "anchor": int(rows[best]),
        "n0res": int(counts[best]),
        "d0": round(d0(int(counts[best])), 4),
        "status": "ok",
        "per_residue": per_residue,
    }


def contact_pairs(a_res: list[dict], b_res: list[dict], distance: float):
    """Unique cross-chain residue pairs whose closest heavy atoms are within `distance`.

    Counted once per residue pair, never weighted by how many atom pairs are close: one
    long arginine making forty contacts must not outvote six residues making one each.
    """
    centres_b = np.asarray([r["xyz"].mean(axis=0) for r in b_res])
    radii_b = np.asarray([float(np.linalg.norm(r["xyz"] - c, axis=1).max())
                          for r, c in zip(b_res, centres_b)])
    pairs = []
    closest = float("inf")
    for i, ra in enumerate(a_res):
        centre_a = ra["xyz"].mean(axis=0)
        radius_a = float(np.linalg.norm(ra["xyz"] - centre_a, axis=1).max())
        # Bounding-sphere prune before the atom-by-atom pass.
        near = np.where(
            np.linalg.norm(centres_b - centre_a, axis=1) <= radius_a + radii_b + distance
        )[0]
        for j in near:
            deltas = ra["xyz"][:, None, :] - b_res[int(j)]["xyz"][None, :, :]
            dmin = float(np.sqrt((deltas ** 2).sum(axis=2)).min())
            closest = min(closest, dmin)
            if dmin <= distance:
                pairs.append((i, int(j), round(dmin, 3)))
    return pairs, (None if closest == float("inf") else round(closest, 3))


def interface_pae(pae, a_idx, b_idx, pairs, a_name="a", b_name="b") -> dict:
    """Contact-interface PAE. Never filtered by the ipSAE cutoff -- see the module docstring."""
    forward, reverse = f"{a_name}->{b_name}", f"{b_name}->{a_name}"
    if not pairs:
        return {"status": "no_contacts", "ipae": None, "median": None,
                "directional": {forward: None, reverse: None}, "contact_pair_count": 0}
    ab = np.asarray([pae[a_idx[i], b_idx[j]] for i, j, _ in pairs], dtype=float)
    ba = np.asarray([pae[b_idx[j], a_idx[i]] for i, j, _ in pairs], dtype=float)
    both = (ab + ba) / 2.0
    return {
        "status": "ok",
        "ipae": round(float(both.mean()), 4),
        "median": round(float(np.median(both)), 4),
        "directional": {forward: round(float(ab.mean()), 4),
                        reverse: round(float(ba.mean()), 4)},
        "contact_pair_count": len(pairs),
    }


def score_complex(pae, residues, *, pae_cutoff, contact_distance,
                  binder_chains=None, target_chains=None, per_residue=False) -> dict:
    if pae.shape[0] != len(residues):
        raise InputError(
            f"PAE is {pae.shape[0]}x{pae.shape[0]} but the structure has {len(residues)} "
            "protein residues. They must correspond 1:1 and in order; a modified residue "
            "occupying two tokens, or a ligand the PAE covers, is the usual cause. "
            "Refusing to guess a mapping."
        )
    chains: dict[str, list[int]] = {}
    for index, residue in enumerate(residues):
        chains.setdefault(residue["chain"], []).append(index)
    names = sorted(chains)

    scoped = bool(binder_chains or target_chains)
    if scoped:
        requested = set(binder_chains or []) | set(target_chains or [])
        unknown = requested - set(names)
        if unknown:
            raise InputError(f"chains {sorted(unknown)} are not in the structure ({names})")
        binder, target = set(binder_chains or []), set(target_chains or [])
        if not binder or not target:
            raise InputError(
                "--binder-chains and --target-chains must each name at least one chain; "
                "the point of the pair is the boundary the headline score may cross"
            )
        if binder & target:
            raise InputError(f"chains {sorted(binder & target)} are both binder and target")
        wanted = [(a, b) for a in sorted(binder) for b in sorted(target)]
    else:
        wanted = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]

    results = []
    for a, b in wanted:
        a_idx = np.asarray(chains[a])
        b_idx = np.asarray(chains[b])
        contacts, closest = contact_pairs([residues[i] for i in a_idx],
                                          [residues[i] for i in b_idx], contact_distance)
        forward = ipsae_directional(pae, a_idx, b_idx, pae_cutoff)
        reverse = ipsae_directional(pae, b_idx, a_idx, pae_cutoff)
        winner = "a_to_b" if forward["score"] >= reverse["score"] else "b_to_a"
        best = forward if winner == "a_to_b" else reverse
        if best["status"] == "ok":
            status = "ok"
        else:
            # Both are a zero. Which zero it is changes what you do next: chains that never
            # touch are a docking failure, chains that touch but never clear the cutoff are
            # a confidence failure.
            status = "no_qualifying_pairs" if contacts else "no_contacts"
        anchor = best["anchor"]
        # Directions are named by chain, never by argument position: the same interface
        # comes out of a scoped and an unscoped run with the chains in opposite order, and
        # an "a_to_b" that silently swaps meaning between two runs of the same data is a
        # number you cannot compare with itself.
        fwd_key, rev_key = f"{a}->{b}", f"{b}->{a}"
        entry = {
            "chain_a": a, "chain_b": b,
            "ipsae": round(best["score"], 6),
            "status": status,
            "winning_direction": (fwd_key if winner == "a_to_b" else rev_key)
                                 if status == "ok" else None,
            "anchor_residue": (f"{residues[anchor]['chain']}:{residues[anchor]['resid']}"
                               if anchor is not None else None),
            "n0res": best["n0res"], "d0": best["d0"],
            "directional": {fwd_key: round(forward["score"], 6),
                            rev_key: round(reverse["score"], 6)},
            "min_interchain_distance": closest,
            "interface_pae": interface_pae(pae, a_idx, b_idx, contacts, a, b),
        }
        if per_residue:
            entry["per_residue"] = {fwd_key: forward["per_residue"],
                                    rev_key: reverse["per_residue"]}
        results.append(entry)

    scorable = [r for r in results if r["status"] == "ok"]
    if scoped and scorable:
        top = max(scorable, key=lambda r: r["ipsae"])
        headline = {"chain_pair": f"{top['chain_a']}-{top['chain_b']}", "ipsae": top["ipsae"],
                    "ranges_over": f"{len(results)} binder x target pairs"}
    elif scoped:
        headline = None
    else:
        headline = None
    return {
        "pae_cutoff": pae_cutoff,
        "contact_distance": contact_distance,
        "chains": {name: len(idx) for name, idx in chains.items()},
        "scope": "binder x target" if scoped else "all pairs",
        "roles": ({"binder": sorted(binder_chains), "target": sorted(target_chains)}
                  if scoped else None),
        "best_cross_interface": headline,
        "headline_note": (
            None if scoped else
            "No headline number: without --binder-chains/--target-chains a maximum over "
            "these pairs could land on a binder-internal interface such as VH-VL."
        ),
        "pairs": results,
    }


# -- fixtures and selftest ---------------------------------------------------


def _fixture_files(tmp: Path):
    """A three-chain complex written out as both PDB and mmCIF, plus its PAE.

    The geometry is a lie about protein structure and the truth about what is under test:
    three parallel ladders of residues at known separations, so every distance, contact
    count and score in the assertions below is exact rather than approximately right.

      H  x=0.0    binder heavy, 30 residues, plus one hydrogen leaning toward L
      L  x=4.0    binder light, 30 residues   -> H-L separation 4.0 A, in contact
      G  x=-4.5   antigen,      40 residues   -> H-G 4.5 A in contact, L-G 8.5 A not

    The PAE says the binder's own VH-VL interface is predicted far better (2 A) than the
    paratope (6/9 A) -- which is the normal case for a real antibody, and the reason a
    maximum taken over every chain pair reports the wrong interface.
    """
    spacing = 3.8
    layout = [("H", 30, 0.0), ("L", 30, 4.0), ("G", 40, -4.5)]
    atoms = []          # (chain, seq, name, element, x, y, z)
    for chain, count, x in layout:
        for i in range(count):
            y = i * spacing
            atoms.append((chain, i + 1, "CA", "C", x, y, 0.0))
            atoms.append((chain, i + 1, "CB", "C", x, y, 1.5))
            if chain == "H":
                # 2.0 A from chain L. If hydrogens were not excluded this would become
                # the H-L minimum distance, and the assertion below would catch it.
                atoms.append((chain, i + 1, "HB1", "H", x + 2.0, y, 0.0))
    # A water: no CA, so it must not consume a PAE row.
    atoms.append(("W", 1, "O", "O", 40.0, 40.0, 40.0))

    pdb = []
    for serial, (ch, seq, name, el, x, y, z) in enumerate(atoms, start=1):
        record = "HETATM" if ch == "W" else "ATOM  "
        resn = "HOH" if ch == "W" else "ALA"
        pdb.append(
            f"{record}{serial:5d} {name:<4s} {resn:>3s} {ch:1s}{seq:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {el:>2s}"
        )
    pdb_path = tmp / "model.pdb"
    pdb_path.write_text("\n".join(pdb) + "\nEND\n")

    # Real files often label chains one way and present them another; the ids a user
    # types are the auth_* ones.
    label_of = {"H": "A", "L": "B", "G": "C", "W": "D"}
    cif = ["data_test", "loop_"] + [
        "_atom_site." + c for c in
        ("group_PDB", "id", "type_symbol", "label_atom_id", "label_comp_id",
         "label_asym_id", "label_seq_id", "Cartn_x", "Cartn_y", "Cartn_z",
         "auth_seq_id", "auth_asym_id")
    ]
    for serial, (ch, seq, name, el, x, y, z) in enumerate(atoms, start=1):
        group = "HETATM" if ch == "W" else "ATOM"
        resn = "HOH" if ch == "W" else "ALA"
        cif.append(f"{group} {serial} {el} {name} {resn} {label_of[ch]} {seq} "
                   f"{x:.3f} {y:.3f} {z:.3f} {seq} {ch}")
    cif.append("#")
    cif_path = tmp / "model.cif"
    cif_path.write_text("\n".join(cif) + "\n")

    n = 100
    pae = np.full((n, n), 30.0)
    for lo, hi in ((0, 30), (30, 60), (60, 100)):
        pae[lo:hi, lo:hi] = 1.0
    pae[0:30, 30:60] = pae[30:60, 0:30] = 2.0      # H-L, the binder's own interface
    pae[0:30, 60:100] = 6.0                         # H->G
    pae[60:100, 0:30] = 9.0                         # G->H, deliberately different
    pae[30:60, 60:100] = pae[60:100, 30:60] = 25.0  # L-G, above any cutoff
    # Two deliberate irregularities inside the H-G block, each pinning one invariant that
    # a uniform block cannot see:
    #   the last 10 columns of G sit at exactly 10.0, the default cutoff, so n0res is 30
    #   per row rather than the 40 residues chain G actually has -- and a cutoff written
    #   `<=` instead of `<` admits them and changes the score;
    #   the last 5 residues of each chain are above the cutoff in BOTH directions while
    #   still in geometric contact, so an iPAE that filters by the cutoff loses five real
    #   contact pairs whichever way round the chain pair is taken.
    pae[0:30, 90:100] = 10.0
    pae[25:30, 60:100] = 20.0
    pae[85:90, 0:30] = 22.0
    pae_path = tmp / "pae.json"
    pae_path.write_text(json.dumps({"pae": pae.tolist()}))
    npz_path = tmp / "pae.npz"
    np.savez(npz_path, predicted_aligned_error=pae)
    return pdb_path, cif_path, pae_path, npz_path


def selftest() -> int:
    import math
    import tempfile

    ok = True

    def check(label, got, want, tol=1e-6):
        nonlocal ok
        good = abs(got - want) < tol if isinstance(want, float) else got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    def expect(pae_value, n0res):
        """The formula written out longhand, so a typo in d0() does not cancel itself."""
        d = 1.0 if n0res < 27 else 1.24 * math.pow(n0res - 15, 1.0 / 3.0) - 1.8
        return 1.0 / (1.0 + (pae_value / d) ** 2)

    print("d0 (formula 15 -- the boundary is where implementations diverge)")
    check("d0(5)", d0(5), 1.0)
    check("d0(26)", d0(26), 1.0)
    check("d0(27)", round(d0(27), 4), 1.0389)
    check("d0(40)", round(d0(40), 4), 1.8258)

    print("directional score")
    pae = np.array([[0.0, 1.0], [20.0, 0.0]])
    out = ipsae_directional(pae, np.array([0]), np.array([1]), 10.0)
    check("one qualifying partner, d0=1", out["score"], 0.5)
    check("n0res", out["n0res"], 1)
    empty = ipsae_directional(pae, np.array([1]), np.array([0]), 10.0)
    check("no qualifying partner is 0, not NaN", empty["score"], 0.0)
    check("and says why", empty["status"], "no_qualifying_pairs")
    asym = np.array([[0.0, 2.0], [8.0, 0.0]])
    fwd = ipsae_directional(asym, np.array([0]), np.array([1]), 10.0)["score"]
    rev = ipsae_directional(asym, np.array([1]), np.array([0]), 10.0)["score"]
    check("asymmetry survives: A->B != B->A", round(fwd, 4) != round(rev, 4), True)

    print("iPAE")
    check("no contacts is null, not zero",
          interface_pae(asym, np.array([0]), np.array([1]), [])["ipae"], None)
    check("and says why",
          interface_pae(asym, np.array([0]), np.array([1]), [])["status"], "no_contacts")
    both = interface_pae(asym, np.array([0]), np.array([1]), [(0, 0, 3.0)])
    check("bidirectional mean of 2 and 8", both["ipae"], 5.0)
    check("contact count reported", both["contact_pair_count"], 1)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        pdb_path, cif_path, pae_path, npz_path = _fixture_files(tmp)
        matrix = load_pae(pae_path)
        residues = load_residues(pdb_path)

        print("parsing")
        check("water without a CA is not a residue", len(residues), 100)
        check("chains", sorted({r["chain"] for r in residues}), ["G", "H", "L"])
        check("mmCIF auth ids are preferred over its label ids",
              [(r["chain"], r["resid"]) for r in load_residues(cif_path)]
              == [(r["chain"], r["resid"]) for r in residues], True)
        check("npz carries the same matrix",
              bool(np.array_equal(load_pae(npz_path), matrix)), True)

        print("end to end, no chain roles given")
        blind = score_complex(matrix, residues, pae_cutoff=10.0, contact_distance=5.0)
        pairs = {f"{p['chain_a']}-{p['chain_b']}": p for p in blind["pairs"]}
        check("every pair reported", sorted(pairs), ["G-H", "G-L", "H-L"])
        check("no headline number is invented", blind["best_cross_interface"], None)
        check("and it says why", bool(blind["headline_note"]), True)
        check("H-L (binder internal)", pairs["H-L"]["ipsae"], round(expect(2.0, 30), 6))
        check("G-H picks the better direction",
              pairs["G-H"]["ipsae"], round(expect(6.0, 30), 6))
        check("...which is H->G, not G->H", pairs["G-H"]["winning_direction"], "H->G")
        check("G->H scored separately",
              pairs["G-H"]["directional"]["G->H"], round(expect(9.0, 30), 6))
        check("n0res is the row's qualifying count, not the partner chain's length",
              pairs["G-H"]["n0res"], 30)
        check("and d0 follows from that count", pairs["G-H"]["d0"], round(d0(30), 4))
        check("anchor names the residue the score came from",
              pairs["G-H"]["anchor_residue"], "H:1")
        check("hydrogens excluded from contact distance",
              pairs["H-L"]["min_interchain_distance"], 4.0)
        check("L-G never touches", pairs["G-L"]["status"], "no_contacts")
        check("so its iPAE is null, not 0", pairs["G-L"]["interface_pae"]["ipae"], None)
        check("contacts are geometric: the 5 above the cutoff are still counted",
              pairs["G-H"]["interface_pae"]["contact_pair_count"], 30)
        check("so iPAE carries them too, and is not the 7.5 of the other 25",
              pairs["G-H"]["interface_pae"]["ipae"], 9.75)
        check("each direction of iPAE reported on its own",
              pairs["G-H"]["interface_pae"]["directional"]["G->H"], 11.1667)
        check("a PAE exactly at the cutoff does not qualify",
              pairs["G-H"]["ipsae"], round(expect(6.0, 30), 6))

        naive_max = max(p["ipsae"] for p in blind["pairs"])
        real = pairs["G-H"]["ipsae"]
        check("a max over all pairs lands on the wrong interface",
              naive_max == pairs["H-L"]["ipsae"] and naive_max > 3 * real, True)

        print("end to end, binder and target declared")
        scoped = score_complex(matrix, residues, pae_cutoff=10.0, contact_distance=5.0,
                               binder_chains=["H", "L"], target_chains=["G"])
        check("binder-internal pair is not scored",
              sorted(f"{p['chain_a']}-{p['chain_b']}" for p in scoped["pairs"]),
              ["H-G", "L-G"])
        check("headline is the real interface",
              scoped["best_cross_interface"]["chain_pair"], "H-G")
        check("at the paratope's own score",
              scoped["best_cross_interface"]["ipsae"], real)
        scoped_gh = [p for p in scoped["pairs"] if {p["chain_a"], p["chain_b"]} == {"G", "H"}][0]
        check("chain order flips between the two runs, as it must",
              (scoped_gh["chain_a"], scoped_gh["chain_b"])
              != (pairs["G-H"]["chain_a"], pairs["G-H"]["chain_b"]), True)
        check("but the direction labels do not, because they name chains",
              scoped_gh["directional"] == pairs["G-H"]["directional"], True)
        check("nor does the winning direction",
              scoped_gh["winning_direction"], pairs["G-H"]["winning_direction"])
        check("roles are recorded", scoped["roles"], {"binder": ["H", "L"], "target": ["G"]})
        check("mmCIF gives the identical report",
              score_complex(load_pae(cif_path.with_name("pae.json")),
                            load_residues(cif_path), pae_cutoff=10.0,
                            contact_distance=5.0, binder_chains=["H", "L"],
                            target_chains=["G"]) == scoped, True)

        # Each refusal is pinned to what it SAYS, not merely that it raised. Two of these
        # conditions are reachable through a second guard that raises a different, less
        # useful message; asserting only the exception type cannot tell them apart.
        print("refusals")
        (tmp / "summary.json").write_text(json.dumps({"iptm": 0.8}))
        for label, call, expected in (
            ("PAE shorter than the structure",
             lambda: score_complex(matrix[:99, :99], residues, pae_cutoff=10.0,
                                   contact_distance=5.0), "must correspond 1:1"),
            ("a chain that is not there",
             lambda: score_complex(matrix, residues, pae_cutoff=10.0, contact_distance=5.0,
                                   binder_chains=["X"], target_chains=["G"]),
             "not in the structure"),
            ("binder named without a target",
             lambda: score_complex(matrix, residues, pae_cutoff=10.0, contact_distance=5.0,
                                   binder_chains=["H"], target_chains=[]),
             "must each name at least one chain"),
            ("a chain on both sides",
             lambda: score_complex(matrix, residues, pae_cutoff=10.0, contact_distance=5.0,
                                   binder_chains=["H"], target_chains=["H"]),
             "both binder and target"),
            ("a file with no PAE in it",
             lambda: load_pae(tmp / "summary.json"), "carries no PAE"),
            ("a path that does not exist",
             lambda: require_file("--pae", tmp / "absent.json"), "no such file"),
            ("a directory where a file belongs",
             lambda: require_file("--structure", tmp), "not a file"),
        ):
            try:
                call()
            except InputError as exc:
                check(f"{label} -> says {expected!r}", expected in str(exc), True)
            else:
                check(label, "no error raised", "InputError")

    print("\n" + ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ipSAE and contact-interface PAE per chain pair, with binder/target roles.")
    parser.add_argument("--pae", type=Path, help="PAE matrix: JSON or .npz")
    parser.add_argument("--structure", type=Path, help="mmCIF or PDB")
    parser.add_argument("--binder-chains", default="",
                        help="comma-separated; with --target-chains, confines scoring to "
                             "pairs that cross the binder/target boundary")
    parser.add_argument("--target-chains", default="")
    parser.add_argument("--pae-cutoff", type=float, default=10.0,
                        help="ipSAE only; 10 and 15 are both in use. Fix one per comparison.")
    parser.add_argument("--contact-distance", type=float, default=5.0,
                        help="iPAE only; independent of --pae-cutoff")
    parser.add_argument("--per-residue", action="store_true",
                        help="include the per-aligned-residue score arrays")
    parser.add_argument("--out", type=Path, help="write the JSON here as well as to stdout")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.pae or not args.structure:
        parser.error("--pae and --structure are both required (or use --selftest)")

    try:
        report = score_complex(
            load_pae(require_file("--pae", args.pae)),
            load_residues(require_file("--structure", args.structure)),
            pae_cutoff=args.pae_cutoff,
            contact_distance=args.contact_distance,
            binder_chains=[c for c in args.binder_chains.split(",") if c],
            target_chains=[c for c in args.target_chains.split(",") if c],
            per_residue=args.per_residue,
        )
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: cannot read an input: {exc}", file=sys.stderr)
        return 2

    report["inputs"] = {
        "pae": {"path": str(args.pae), "sha256": sha256(args.pae)},
        "structure": {"path": str(args.structure), "sha256": sha256(args.structure)},
    }
    text = json.dumps(report, indent=2)
    if args.out:
        try:
            args.out.write_text(text + "\n")
        except OSError as exc:
            print(f"error: cannot write --out: {exc}", file=sys.stderr)
            return 2
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
