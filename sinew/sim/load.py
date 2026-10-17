"""Load a simulated store into its graph through the real pipeline, then run the daily jobs once.

    uv run python -m sinew.sim.load northwind            # into the graph .env points at (cloud)
    SINEW_LOCAL=1 uv run python -m sinew.sim.load northwind   # into local docker
"""

import json
import sys
import time
from pathlib import Path

from sinew import schema
from sinew.db import client, graph
from sinew.engine import assumptions, identity, promises, snapshot
from sinew.engine.sdk import SinewClient
from sinew.sim import privacy_check
from sinew.sim.northwind import NOW, ROOT


def load(tenant: str, fresh: bool = True) -> dict:
    if fresh and tenant in client().list_graphs():
        graph(tenant).delete()
    schema.apply(tenant)
    events = [json.loads(line) for line in Path(ROOT / "events" / f"{tenant}.jsonl").read_text().splitlines()]
    started = time.time()
    sdk = SinewClient(None, tenant)  # in-process: same pipeline as the signed HTTP endpoint
    totals = {"accepted": 0, "stale": 0, "quarantined": 0}
    for i in range(0, len(events), 500):
        r = sdk.send(events[i:i + 500])
        totals["accepted"] += r["accepted"]
        totals["stale"] += r["stale"]
        totals["quarantined"] += len(r["quarantined"])
        print(f"  {min(i + 500, len(events))}/{len(events)} events  {time.time() - started:.0f}s", flush=True)
    from sinew.sim import docs
    r = sdk.send(docs.events(tenant))  # the documents the company allows Sinew to read
    totals["accepted"] += r["accepted"]
    totals["quarantined"] += len(r["quarantined"])
    g = graph(tenant)
    g.query("MERGE (m:Meta {id: 'clock'}) SET m.now = $now", {"now": NOW})  # the demo's "today"
    checks = assumptions.evaluate(tenant, now=NOW)
    broken_promises = promises.sweep(tenant, now=NOW)
    nodes = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    edges = g.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    merged = identity.merge(tenant)
    privacy = privacy_check.scan(tenant)
    if privacy["leaks"]:
        raise SystemExit(f"PRIVACY CHECK FAILED: {privacy['leaks'][:5]}")
    snapshot_bytes = snapshot.save(tenant)  # only a graph that passed the privacy scan becomes the refill
    return {"tenant": tenant, **totals, "privacy": {"checked": privacy["personal_values_checked"], "leaks": 0},
            "identity": merged, "snapshot_kb": snapshot_bytes // 1024, "seconds": round(time.time() - started), "nodes": nodes, "edges": edges,
            "assumptions": checks, "promises_broken_now": broken_promises}


if __name__ == "__main__":
    print(json.dumps(load(sys.argv[1] if len(sys.argv) > 1 else "northwind"), indent=1))
