#!/usr/bin/env python3
"""Did the binder land where you told it to?

Hotspot conditioning is a request, not a constraint. The folder is free to place the
binder somewhere else entirely and still report a confident interface. So measure the
thing you actually asked for: what fraction of the hotspot residues the binder touches.

The word "contact" is the whole difficulty here. Three definitions are in common use,
they differ by more than a factor of two in distance, and they are NOT interchangeable:

  heavy-5   any non-hydrogen atom within 5 A of any non-hydrogen atom. The closest
            thing to a physical contact -- van der Waals contact is ~4 A.
  cb-8      CB within 8 A of CB. The CASP/contact-prediction convention. A residue pair
            can satisfy this with their side chains pointing in opposite directions.
  cb-13     CB within 13 A of CB. The neighbourhood used by RFdiffusion-family hotspot
            conditioning. This is a NEIGHBOURHOOD, not a contact -- 13 A is roughly two
            residues apart in space, and quoting it as "in contact" overstates the result.

This script makes you name one and prints which you used. Glycine has no CB; CA is
substituted, and the count of substitutions is reported because it shifts the distance.

Stdlib + numpy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

DEFINITIONS = {
    "heavy-5": (5.0, "any non-hydrogen atom pair within 5 A (physical contact)"),
    "cb-8": (8.0, "CB-CB within 8 A (CASP contact-prediction convention)"),
    "cb-13": (13.0, "CB-CB within 13 A (RFdiffusion hotspot NEIGHBOURHOOD, not a contact)"),
}


class InputError(RuntimeError):
    pass


def parse_atoms(path: Path) -> dict[str, dict[str, list]]:
    """{chain: {resid: [(atom_name, element, x, y, z), ...]}} for a PDB file."""
    if not path.is_file():
        raise InputError(f"{path}: no such file")
    out: dict[str, dict[str, list]] = {}
    for ln in path.read_text().splitlines():
        if not ln.startswith("ATOM  "):
            continue
        name = ln[12:16].strip()
        elem = (ln[76:78].strip() or name[:1]).upper()
        ch = ln[21:22].strip() or "A"
        out.setdefault(ch, {}).setdefault(ln[22:27].strip(), []).append(
            (name, elem, float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
    if not out:
        raise InputError(f"{path.name}: no ATOM records")
    return out


def _points(atoms: list, definition: str) -> tuple[np.ndarray, bool]:
    """Points for one residue, and whether a CB substitution was needed."""
    if definition == "heavy-5":
        return np.array([a[2:] for a in atoms if a[1] != "H"], dtype=float), False
    cb = [a for a in atoms if a[0] == "CB"]
    if cb:
        return np.array([cb[0][2:]], dtype=float), False
    ca = [a for a in atoms if a[0] == "CA"]
    if not ca:
        return np.empty((0, 3)), False
    return np.array([ca[0][2:]], dtype=float), True   # glycine, or a CB-less model


def contacts(structure: Path, binder_chains: list[str], target_chains: list[str],
             hotspots: list[str], definition: str) -> dict:
    if definition not in DEFINITIONS:
        raise InputError(f"unknown definition {definition!r}; pick one of {sorted(DEFINITIONS)}")
    cutoff, meaning = DEFINITIONS[definition]
    st = parse_atoms(structure)

    missing = [c for c in binder_chains + target_chains if c not in st]
    if missing:
        raise InputError(f"chain(s) {missing} are not in {structure.name}; it has {sorted(st)}")
    if set(binder_chains) & set(target_chains):
        raise InputError("a chain is listed as both binder and target; "
                         "every residue would then contact itself")

    subs = 0
    binder_pts = []
    for c in binder_chains:
        for atoms in st[c].values():
            p, s = _points(atoms, definition)
            subs += s
            if len(p):
                binder_pts.append(p)
    if not binder_pts:
        raise InputError("the binder chains contributed no atoms")
    B = np.vstack(binder_pts)

    known = {r for c in target_chains for r in st[c]}
    absent = [h for h in hotspots if h not in known]
    if absent:
        raise InputError(
            f"hotspot residue(s) {absent} are not in target chain(s) {target_chains}. "
            "Hotspots must be numbered as they appear in THIS file -- a renumbered "
            "target silently turns every hotspot into a miss."
        )

    per_hotspot, touched = {}, 0
    for h in hotspots:
        pts, s = _points(next(st[c][h] for c in target_chains if h in st[c]), definition)
        subs += s
        if not len(pts):
            per_hotspot[h] = {"contacted": False, "min_distance": None,
                              "note": "no usable atom for this residue"}
            continue
        d = float(np.sqrt(((B[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).min())
        hit = d <= cutoff
        touched += hit
        per_hotspot[h] = {"contacted": bool(hit), "min_distance": round(d, 2)}

    return {
        "definition": definition,
        "cutoff_angstrom": cutoff,
        "definition_means": meaning,
        "hotspots_requested": len(hotspots),
        "hotspots_contacted": touched,
        "fraction_contacted": round(touched / len(hotspots), 4) if hotspots else None,
        "per_hotspot": per_hotspot,
        "cb_substituted_with_ca": subs,
        "caveat": ("this measures where the binder IS, not whether it binds. A contacted "
                   "hotspot with a bad interface is still a bad design."),
    }


def _selftest() -> int:
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    import tempfile  # noqa: PLC0415
    tmp = Path(tempfile.mkdtemp())

    def write(path, rows):
        (tmp / path).write_text("\n".join(
            f"ATOM  {n:5d}  {nm:<3s} {res} {ch}{ri:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           {nm[0]}"
            for n, (nm, res, ch, ri, x, y, z) in enumerate(rows, start=1)) + "\nEND\n")
        return tmp / path

    # binder CB at x=0; target CBs walked out to known distances
    rows = [("CA", "ALA", "A", 1, 0.0, 0.0, 0.0), ("CB", "ALA", "A", 1, 0.0, 0.0, 0.0)]
    for i, dist in enumerate([4.0, 7.0, 12.0, 20.0], start=1):
        rows += [("CA", "ALA", "B", i, dist, 0.0, 0.0), ("CB", "ALA", "B", i, dist, 0.0, 0.0)]
    f = write("c.pdb", rows)

    print("each definition counts a different set -- distances chosen to separate them")
    for d, want in [("heavy-5", 1), ("cb-8", 2), ("cb-13", 3)]:
        r = contacts(f, ["A"], ["B"], ["1", "2", "3", "4"], d)
        check(f"{d} contacts {want} of 4", r["hotspots_contacted"], want)
    r = contacts(f, ["A"], ["B"], ["1", "2", "3", "4"], "cb-13")
    check("fraction matches the count", r["fraction_contacted"], 0.75)
    check("exact distance survives to the report", r["per_hotspot"]["3"]["min_distance"], 12.0)
    check("13 A is labelled a neighbourhood", "NEIGHBOURHOOD" in r["definition_means"], True)

    print("the cutoff is inclusive at exactly the boundary")
    edge = write("e.pdb", [("CB", "ALA", "A", 1, 0.0, 0.0, 0.0),
                           ("CB", "ALA", "B", 1, 8.0, 0.0, 0.0)])
    check("CB-CB at exactly 8.0 A counts under cb-8",
          contacts(edge, ["A"], ["B"], ["1"], "cb-8")["hotspots_contacted"], 1)
    check("and does not count under heavy-5",
          contacts(edge, ["A"], ["B"], ["1"], "heavy-5")["hotspots_contacted"], 0)

    print("hydrogens are not heavy atoms, even when they are the nearest atom")
    # Every other fixture is hydrogen-free, so dropping the element filter changes nothing
    # in them. Here the only atom within 5 A is an H: heavy-5 must still say no contact.
    hyd = write("h.pdb", [("CB", "ALA", "A", 1, 0.0, 0.0, 0.0),
                          ("H", "ALA", "B", 1, 3.0, 0.0, 0.0),
                          ("CB", "ALA", "B", 1, 7.0, 0.0, 0.0)])
    check("an H at 3 A does not make a heavy-atom contact",
          contacts(hyd, ["A"], ["B"], ["1"], "heavy-5")["hotspots_contacted"], 0)
    check("and the heavy atom at 7 A is what gets reported",
          contacts(hyd, ["A"], ["B"], ["1"], "heavy-5")["per_hotspot"]["1"]["min_distance"], 7.0)

    print("the CLOSEST binder atom decides, not the average one")
    # With one binder atom, min and mean are identical and a swap is undetectable.
    two = write("t.pdb", [("CB", "ALA", "A", 1, 0.0, 0.0, 0.0),
                          ("CB", "ALA", "A", 2, 100.0, 0.0, 0.0),
                          ("CB", "ALA", "B", 1, 4.0, 0.0, 0.0)])
    r2 = contacts(two, ["A"], ["B"], ["1"], "cb-8")
    check("a distant second binder residue does not dilute the contact",
          r2["hotspots_contacted"], 1)
    check("the reported distance is the minimum", r2["per_hotspot"]["1"]["min_distance"], 4.0)

    print("glycine has no CB, and the substitution is counted not hidden")
    gly = write("g.pdb", [("CB", "ALA", "A", 1, 0.0, 0.0, 0.0),
                          ("CA", "GLY", "B", 1, 7.0, 0.0, 0.0)])
    rg = contacts(gly, ["A"], ["B"], ["1"], "cb-8")
    check("CA stands in for the missing CB", rg["hotspots_contacted"], 1)
    check("and the substitution is reported", rg["cb_substituted_with_ca"], 1)

    print("wrong numbering is refused, not scored as a miss")
    for bad, needle in [(["99"], "not in target"), ([], None)]:
        if not bad:
            continue
        try:
            contacts(f, ["A"], ["B"], bad, "cb-8")
        except InputError as exc:
            check("an absent hotspot id is refused", needle in str(exc), True)
            check("and the reason names renumbering", "renumbered" in str(exc), True)
        else:
            check("an absent hotspot id is refused", "no refusal", "InputError")

    try:
        contacts(f, ["A"], ["A"], ["1"], "cb-8")
    except InputError as exc:
        check("a chain cannot be both binder and target", "both binder and target" in str(exc), True)
    else:
        check("a chain cannot be both binder and target", "no refusal", "InputError")

    try:
        contacts(f, ["Z"], ["B"], ["1"], "cb-8")
    except InputError as exc:
        check("an absent chain is refused", "not in" in str(exc), True)
    else:
        check("an absent chain is refused", "no refusal", "InputError")

    try:
        contacts(f, ["A"], ["B"], ["1"], "within-10")
    except InputError as exc:
        check("an invented definition is refused", "unknown definition" in str(exc), True)
    else:
        check("an invented definition is refused", "no refusal", "InputError")

    print("\n" + ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--structure", type=Path, help="the complex, as a PDB file")
    p.add_argument("--binder-chains", default="")
    p.add_argument("--target-chains", default="")
    p.add_argument("--hotspots", default="", help="target residue ids as numbered in THIS file")
    p.add_argument("--definition", default="cb-13", choices=sorted(DEFINITIONS))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        return _selftest()
    if not args.structure:
        p.error("--structure is required (or use --selftest)")
    try:
        r = contacts(args.structure,
                     [c for c in args.binder_chains.split(",") if c],
                     [c for c in args.target_chains.split(",") if c],
                     [h for h in args.hotspots.split(",") if h],
                     args.definition)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
