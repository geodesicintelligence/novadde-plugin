#!/usr/bin/env python3
"""Which residues a surface binder may actually target, and which are unreachable.

The trap this exists for: UniProt's `Binding site` and `Active site` features annotate
CATALYTIC chemistry. On a single-pass receptor that chemistry is usually INTRACELLULAR, so
an agent asked to "pick hotspots" reaches for those features and aims the design at a pocket
no antibody can reach.

HER2 (P04626) is the worked example, and it is the canonical antibody target:

    Topological domain   23-652      Extracellular
    Transmembrane        653-675
    Topological domain   676-1255    Cytoplasmic
    Active site          845         Proton acceptor
    Binding site         726-734, 753

Every annotated site is cytoplasmic. Trastuzumab binds domain IV, around 563-626 -- which
carries no site annotation at all. The features that look most like "the functional bit" are
exactly the ones a binder cannot use.

So this script classifies every annotated feature by the topological domain it falls in, and
refuses to hand back a candidate that is not on the reachable side of the membrane.

Network for --accession (UniProt REST). --selftest is offline.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

UNIPROT = "https://rest.uniprot.org/uniprotkb/{acc}.json"
FIELDS = "accession,protein_name,ft_binding,ft_act_site,ft_site,ft_topo_dom,ft_transmem,ft_signal,ft_mutagen"

#: Features that read as "the functional site" and are the usual wrong answer on a receptor.
CATALYTIC = ("Active site", "Binding site", "Site")
#: Features whose description often records an actual binding/interaction experiment.
EXPERIMENTAL = ("Mutagenesis",)


class InputError(RuntimeError):
    """Something about the inputs is wrong in a way guessing would not fix."""


def fetch(accession: str) -> dict:
    url = UNIPROT.format(acc=accession) + "?fields=" + FIELDS
    try:
        with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise InputError(f"could not read UniProt for {accession}: {exc}") from exc


def spans(entry: dict) -> list[dict]:
    """Every feature as {type, start, end, description}."""
    out = []
    for f in entry.get("features", []):
        loc = f.get("location", {})
        s = (loc.get("start") or {}).get("value")
        e = (loc.get("end") or {}).get("value")
        if s is None or e is None:
            continue
        out.append({"type": f["type"], "start": int(s), "end": int(e),
                    "description": f.get("description") or ""})
    return out


def topology(features: list[dict]) -> list[dict]:
    """The topological domains, in order. Empty for a soluble protein -- which is not an
    error, it means the membrane question does not apply."""
    return [f for f in features if f["type"] == "Topological domain"]


def locate(position: int, topo: list[dict], features: list[dict]) -> str:
    """Which side of the membrane a residue is on."""
    for t in topo:
        if t["start"] <= position <= t["end"]:
            return t["description"] or "unannotated topological domain"
    for f in features:
        if f["type"] == "Transmembrane" and f["start"] <= position <= f["end"]:
            return "Transmembrane"
        if f["type"] == "Signal" and f["start"] <= position <= f["end"]:
            return "Signal peptide"
    return "outside every annotated domain"


def assess(entry: dict, reachable: str = "Extracellular") -> dict:
    features = spans(entry)
    topo = topology(features)
    name = ((entry.get("proteinDescription", {}).get("recommendedName", {})
             .get("fullName", {})) or {}).get("value", "")

    accessible = [t for t in topo if reachable.lower() in (t["description"] or "").lower()]
    rows = []
    for f in features:
        if f["type"] not in CATALYTIC + EXPERIMENTAL:
            continue
        where = locate(f["start"], topo, features)
        ok = reachable.lower() in where.lower()
        rows.append({
            "feature": f["type"],
            "span": str(f["start"]) if f["start"] == f["end"] else f"{f['start']}-{f['end']}",
            "description": f["description"][:70],
            "topology": where,
            "reachable_by_a_surface_binder": ok if topo else None,
        })

    verdict = {
        "accession": entry.get("primaryAccession"),
        "protein": name,
        "membrane_protein": bool(topo),
        "reachable_region": [f"{t['start']}-{t['end']}" for t in accessible] or None,
        "annotated_sites": rows,
    }
    if not topo:
        verdict["note"] = ("No topological domains annotated. Either a soluble protein, where "
                           "the membrane question does not arise, or an entry whose topology "
                           "is simply not curated -- those are different, and this cannot tell "
                           "them apart. Check before treating every site as reachable.")
        return verdict

    unreachable = [r for r in rows if r["reachable_by_a_surface_binder"] is False]
    if rows and not any(r["reachable_by_a_surface_binder"] for r in rows):
        verdict["warning"] = (
            f"EVERY annotated site ({len(rows)}) is outside the {reachable.lower()} region. "
            "These features annotate catalytic chemistry, not a binder epitope. Targeting them "
            "aims the design at a surface the binder cannot reach. Choose an epitope inside "
            f"{verdict['reachable_region']} on other grounds -- a known therapeutic epitope, a "
            "co-crystal, or a surface patch -- and validate it against the structure."
        )
    elif unreachable:
        verdict["warning"] = (
            f"{len(unreachable)} of {len(rows)} annotated sites are outside the "
            f"{reachable.lower()} region and must not be used as hotspots."
        )
    return verdict


def check_residues(residues: list[int], entry: dict, reachable: str = "Extracellular") -> dict:
    """Validate chosen residues against the topology."""
    features = spans(entry)
    topo = topology(features)
    rows = []
    for p in residues:
        where = locate(p, topo, features)
        rows.append({"residue": p, "topology": where,
                     "reachable": (reachable.lower() in where.lower()) if topo else None})
    bad = [r["residue"] for r in rows if r["reachable"] is False]
    out = {"residues": rows}
    if bad:
        out["refused"] = (f"residues {bad} are not in the {reachable.lower()} region; a surface "
                          "binder cannot reach them")
    return out


def _selftest() -> int:
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    # HER2 P04626, transcribed from the live UniProt entry on 2026-09-15.
    her2 = {"primaryAccession": "P04626",
            "proteinDescription": {"recommendedName": {"fullName": {"value": "erbB-2"}}},
            "features": [
                {"type": "Signal", "location": {"start": {"value": 1}, "end": {"value": 22}}},
                {"type": "Topological domain", "description": "Extracellular",
                 "location": {"start": {"value": 23}, "end": {"value": 652}}},
                {"type": "Transmembrane", "description": "Helical",
                 "location": {"start": {"value": 653}, "end": {"value": 675}}},
                {"type": "Topological domain", "description": "Cytoplasmic",
                 "location": {"start": {"value": 676}, "end": {"value": 1255}}},
                {"type": "Active site", "description": "Proton acceptor",
                 "location": {"start": {"value": 845}, "end": {"value": 845}}},
                {"type": "Binding site",
                 "location": {"start": {"value": 726}, "end": {"value": 734}}},
                {"type": "Binding site",
                 "location": {"start": {"value": 753}, "end": {"value": 753}}},
            ]}

    print("the HER2 trap, which is the whole reason this exists")
    v = assess(her2)
    check("it is a membrane protein", v["membrane_protein"], True)
    check("the reachable region is the ectodomain", v["reachable_region"], ["23-652"])
    check("three annotated sites", len(v["annotated_sites"]), 3)
    check("none of them is reachable",
          any(r["reachable_by_a_surface_binder"] for r in v["annotated_sites"]), False)
    check("and it says so loudly", "EVERY annotated site" in v.get("warning", ""), True)
    for row in v["annotated_sites"]:
        check(f"{row['feature']} {row['span']} is cytoplasmic", row["topology"], "Cytoplasmic")

    print("boundaries are inclusive and the membrane is not a rounding error")
    check("652 is the last extracellular residue", locate(652, topology(spans(her2)), spans(her2)),
          "Extracellular")
    check("653 is already membrane", locate(653, topology(spans(her2)), spans(her2)),
          "Transmembrane")
    check("676 is the first cytoplasmic residue",
          locate(676, topology(spans(her2)), spans(her2)), "Cytoplasmic")
    check("a signal-peptide residue is named as such",
          locate(10, topology(spans(her2)), spans(her2)), "Signal peptide")

    print("choosing residues is checked against the same topology")
    r = check_residues([300, 845], her2)
    check("an ectodomain residue passes", r["residues"][0]["reachable"], True)
    check("the active site does not", r["residues"][1]["reachable"], False)
    check("and the refusal names it", "[845]" in r.get("refused", ""), True)

    print("a soluble protein is not silently treated as reachable")
    soluble = {"primaryAccession": "X", "features": [
        {"type": "Active site", "location": {"start": {"value": 50}, "end": {"value": 50}}}]}
    s = assess(soluble)
    check("no topology means no verdict", s["annotated_sites"][0]["reachable_by_a_surface_binder"],
          None)
    check("and it says the two cases are different", "different" in s.get("note", ""), True)
    check("no false warning", "warning" in s, False)

    print("\n" + ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--accession", help="UniProt accession, e.g. P04626")
    p.add_argument("--residues", help="comma-separated residue numbers to validate")
    p.add_argument("--reachable", default="Extracellular",
                   help="which topological domain a binder can reach (default: Extracellular)")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        return _selftest()
    if not args.accession:
        p.error("--accession is required (or use --selftest)")
    try:
        entry = fetch(args.accession)
        report = assess(entry, args.reachable)
        if args.residues:
            picks = [int(x) for x in args.residues.split(",") if x.strip()]
            report["your_residues"] = check_residues(picks, entry, args.reachable)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError:
        print("error: --residues must be comma-separated integers", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
