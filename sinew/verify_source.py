"""Does the graph agree with the source data it was built from?

Reads the raw event feed (seed/events/<tenant>.jsonl: what the store, helpdesk and courier systems sent) with plain
Python, computes totals straight from it, then asks the graph the same questions with Cypher. Nothing here uses the
graph to compute the expected value, so a loading bug cannot hide behind itself.

    SINEW_LOCAL=1 uv run python -m sinew.verify_source [tenant]
"""

import json
import sys
from collections import Counter
from pathlib import Path

from sinew.db import graph

SEED = Path(__file__).resolve().parents[1] / "seed" / "events"


def source(tenant: str) -> dict:
    ev = [json.loads(line) for line in (SEED / f"{tenant}.jsonl").read_text().splitlines() if line.strip()]
    by = lambda t: [e for e in ev if e["type"] == t]
    status = {}
    for e in sorted(by("order.placed") + by("order.updated"), key=lambda e: e["occurred_at"]):
        status[e["payload"]["order_id"]] = e["payload"]["status"]
    orders = by("order.placed")
    ship_courier = {e["payload"]["shipment_id"]: e["payload"]["courier_id"] for e in by("shipment.created")}
    return {
        "orders": len(orders),
        "order revenue": round(sum(e["payload"]["total"] for e in orders), 2),
        "order lines": sum(len(e["payload"]["lines"]) for e in orders),
        "orders delivered": sum(1 for s in status.values() if s == "delivered"),
        "payments captured": round(sum(e["payload"]["amount"] for e in by("payment.captured")), 2),
        "shipments": len(ship_courier),
        "tickets": len(by("ticket.created")),
        "refunds issued": len(by("refund.issued")),
        "refund total": round(sum(e["payload"]["amount"] for e in by("refund.issued")), 2),
        "returns": len(by("return.created")),
        "scans": len(by("scan.recorded")),
        **{f"shipments via {c}": n for c, n in sorted(Counter(ship_courier.values()).items())},
        **{f"scans at {h}": n for h, n in sorted(Counter(e["payload"]["hub_id"] for e in by("scan.recorded")).items())},
        **{f"tickets: {k}": n for k, n in sorted(Counter(e["payload"]["issue_type"] for e in by("ticket.created")).items())},
    }


def in_graph(tenant: str, expected: dict) -> dict:
    g = graph(tenant)
    one = lambda q, p=None: g.ro_query(q, p or {}).result_set[0][0]
    got = {
        "orders": one("MATCH (o:Order) RETURN count(o)"),
        "order revenue": round(one("MATCH (o:Order) RETURN sum(o.total)"), 2),
        "order lines": one("MATCH (l:LineItem) RETURN count(l)"),
        "orders delivered": one("MATCH (o:Order {status: 'delivered'}) RETURN count(o)"),
        "payments captured": round(one("MATCH (p:Payment) RETURN sum(p.amount)"), 2),
        "shipments": one("MATCH (s:Shipment) RETURN count(s)"),
        "tickets": one("MATCH (t:Ticket) RETURN count(t)"),
        "refunds issued": one("MATCH (r:Refund) RETURN count(r)"),
        "refund total": round(one("MATCH (r:Refund) RETURN sum(r.amount)"), 2),
        "returns": one("MATCH (r:Return) RETURN count(r)"),
        "scans": one("MATCH (s:Scan) RETURN count(s)"),
    }
    for k in expected:
        if k.startswith("shipments via "):
            got[k] = one("MATCH (:Shipment)-[:VIA]->(c:Courier {id: $c}) RETURN count(*)", {"c": k.removeprefix("shipments via ")})
        elif k.startswith("scans at "):
            got[k] = one("MATCH (:Scan)-[:AT]->(h:Hub {id: $h}) RETURN count(*)", {"h": k.removeprefix("scans at ")})
        elif k.startswith("tickets: "):
            got[k] = one("MATCH (t:Ticket {issue_type: $i}) RETURN count(t)", {"i": k.removeprefix("tickets: ")})
    return got


if __name__ == "__main__":
    tenant = (sys.argv + ["northwind"])[1]
    want = source(tenant)
    have = in_graph(tenant, want)
    bad = 0
    for k, v in want.items():
        ok = abs(have[k] - v) < 0.005
        bad += not ok
        print(f"{'OK  ' if ok else 'DIFF'} {k:34s} source={v:<12} graph={have[k]}")
    print(f"\n{len(want) - bad} of {len(want)} totals match the source data")
    sys.exit(1 if bad else 0)
