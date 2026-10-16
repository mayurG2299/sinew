"""Scan a loaded graph for any personal value held in the store's own records. Expected result: 0 leaks."""

import json
import re

from sinew.db import graph, read_all
from sinew.sim.northwind import ROOT


def needles(tenant: str) -> set[str]:
    personal = json.loads((ROOT / "source" / f"{tenant}_personal.json").read_text())
    out = set()
    for kind in personal.values():
        for rec in kind.values():
            for k, v in rec.items():
                if k in ("name", "display_name"):
                    out.update(p.lower() for p in v.split() if len(p) > 3)
                elif k == "phone":
                    out.add(re.sub(r"\D", "", v)[-7:])
                elif k == "address":
                    street = re.sub(r"^\d+\s*", "", v.split(",")[0]).strip().lower()
                    if len(street) > 6:
                        out.add(street)
                else:
                    out.add(v.lower())
    return out


def scan(tenant: str) -> dict:
    g = graph(tenant)
    rows = []
    for label, props in read_all(g, "(n)", "labels(n)[0], properties(n)"):
        if label != "Product":  # product titles share words with some surnames ("Kettlebell")
            rows += [(label, k, v) for k, v in props.items()]
    for rel, props in read_all(g, "()-[r]->()", "type(r), properties(r)", alias="r"):
        rows += [(rel, k, v) for k, v in props.items()]
    found = needles(tenant)
    # One combined pattern, longest first, one pass per value (a loop per needle is ~90M regex calls).
    pattern = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(n) for n in sorted(found, key=len, reverse=True))
                         + r")(?![a-z0-9])")
    leaks = [(label, key, str(val)[:80], m.group(1)) for label, key, val in rows
             if (m := pattern.search(str(val).lower()))]
    return {"personal_values_checked": len(found), "graph_values_scanned": len(rows), "leaks": leaks}
