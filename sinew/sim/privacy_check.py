"""Scan a loaded graph for any personal value held in the store's own records. Expected result: 0 leaks."""

import json
import re

from sinew.db import graph
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
    rows = g.ro_query("MATCH (n) WHERE NOT n:Product UNWIND keys(n) AS k RETURN labels(n)[0], k, n[k]").result_set
    rows += g.ro_query("MATCH ()-[r]->() UNWIND keys(r) AS k RETURN type(r), k, r[k]").result_set
    found = needles(tenant)
    leaks = [(label, key, str(val)[:80]) for label, key, val in rows for n in found
             if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", str(val).lower())]
    return {"personal_values_checked": len(found), "leaks": leaks}
