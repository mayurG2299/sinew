"""Scale test: Northwind's 30 days of events repeated 10 times further back in time (300 days of history),
loaded into the scratch tenant "sandbox" through the real pipeline, then the speed-pass query forms compared.

    SINEW_LOCAL=1 HASH_KEY_SANDBOX=<hex> uv run python -m sinew.scale

Shared things (staff, teams, hubs, couriers, catalogue, decisions, campaigns) stay one set; customers, orders,
parcels, scans, tickets and promises get a copy per 30-day block.
"""

import copy
import json
import os
import re
import statistics
import time

from sinew import config, schema
from sinew.db import client, graph
from sinew.engine import pipeline
from sinew.sim.northwind import NOW, ROOT

COPIES = 10
SHIFT = 30 * 86_400
PER_COPY = re.compile(r"^(o|sh|t|pf|pr|rf|rt|pay|l|cu)-")  # ids that belong to one 30-day block
TIME_FIELDS = {"placed_at", "promised_at", "due_at", "since", "made_at", "starts", "ends"}
SHARED_TYPES = {"team.upserted", "staff.upserted", "supplier.upserted", "product.upserted", "batch.upserted",
                "courier.upserted", "hub.upserted", "route.upserted", "warehouse.upserted", "decision.recorded",
                "campaign.upserted"}


def _rename(value, k: int):
    if isinstance(value, str) and PER_COPY.match(value):
        return f"{value}~{k}"
    if isinstance(value, list):
        return [_rename(v, k) for v in value]
    if isinstance(value, dict):
        return {key: _rename(v, k) for key, v in value.items()}
    return value


def events() -> list[dict]:
    base = [json.loads(line) for line in (ROOT / "events" / "northwind.jsonl").read_text().splitlines()]
    out = [e for e in base if e["type"] in SHARED_TYPES]
    for k in range(COPIES):
        for e in base:
            if e["type"] in SHARED_TYPES:
                continue
            e = copy.deepcopy(e)
            e["event_id"] = f"{e['event_id']}~{k}"
            e["occurred_at"] -= k * SHIFT
            p = _rename(e["payload"], k)
            for f in TIME_FIELDS & p.keys():
                p[f] -= k * SHIFT
            if k and e["type"] == "scan.recorded" and p.get("status") == "delayed":
                p["status"], p["late_hours"] = "in_transit", 0  # only the newest block has the sale-week delays
            e["payload"] = p
            out.append(e)
    out.sort(key=lambda e: e["occurred_at"])
    return out


def load() -> dict:
    os.environ.setdefault("HASH_KEY_SANDBOX", "5a" * 32)
    config.TENANTS = (*config.TENANTS, "sandbox")
    if "sandbox" in client().list_graphs():
        graph("sandbox").delete()
    schema.apply("sandbox")
    evs = events()
    start = time.time()
    for i in range(0, len(evs), 2000):
        pipeline.process("sandbox", evs[i:i + 2000])
    graph("sandbox").query("MERGE (m:Meta {id: 'clock'}) SET m.now = $n", {"n": NOW})
    g = graph("sandbox")
    return {"events": len(evs), "seconds": round(time.time() - start),
            "nodes": g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0],
            "edges": g.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]}


def compare() -> list[dict]:
    from sinew import perf

    rows = []
    for label in ("before", "after"):
        perf.AFTER = label == "after"
        for r in perf.run("sandbox", f"scale-{label}"):
            rows.append({"form": label, **{k: r[k] for k in ("query", "median_ms", "max_rows_in_a_step")}})
    return rows


if __name__ == "__main__":
    print(load())
    for r in compare():
        print(f"{r['form']:6} {r['median_ms']:8.3f} ms {r['max_rows_in_a_step']:7d} rows  {r['query']}")
