"""Promise lifecycle (decision 3): proposed -> open (a person confirmed it) -> kept / kept_late / broken.

A promise also counts as confirmed when the matching action happens: a refund on the same order for a
refund promise, a delivered scan for a delivery promise. Nothing is decided by the AI here.
"""

import time

from falkordb import Graph

from sinew.db import graph

_MATCH_ACTION = {
    "refund": "MATCH (p)-[:CONCERNS]->(o:Order)<-[:FOR]-(act:Refund) WHERE act.status = 'issued'",
    "delivery": "MATCH (p)-[:CONCERNS]->(o:Order)-[:SHIPPED_AS]->(:Shipment)<-[:FOR]-(act:Scan) "
                "WHERE act.status = 'delivered'",
}


def match_actions(g: Graph, order_id: str):
    """Called when a refund or a scan arrives: settle the order's promises that this action fulfils."""
    for kind, pattern in _MATCH_ACTION.items():
        g.query(
            "MATCH (p:Promise {kind: $kind})-[:CONCERNS]->(:Order {id: $o}) "
            "WHERE p.status IN ['proposed', 'open'] "
            f"WITH p {pattern} AND o.id = $o "
            "WITH p, act ORDER BY act.at LIMIT 1 "
            "MERGE (p)-[:KEPT_BY]->(act) "
            "SET p.status = CASE WHEN act.at <= p.due_at THEN 'kept' ELSE 'kept_late' END, "
            "    p.settled_at = act.at, p.confirmed_by = coalesce(p.confirmed_by, 'action')",
            {"kind": kind, "o": order_id},
        )


def sweep(tenant: str, now: int | None = None) -> int:
    """Mark open promises past their deadline as broken. Proposed-but-unconfirmed ones are left alone."""
    g = graph(tenant)
    now = now or int(time.time())
    return g.query(
        "MATCH (p:Promise {status: 'open'}) WHERE p.due_at < $now "
        "SET p.status = 'broken', p.broken_at = $now RETURN count(p)",
        {"now": now},
    ).result_set[0][0]


def due_soon(tenant: str, now: int, within_s: int = 86_400) -> list[list]:
    """Open promises due within the window with no action yet: the 24 h nudge."""
    return graph(tenant).ro_query(
        "MATCH (p:Promise {status: 'open'})-[:MADE_BY]->(u:User) "
        "WHERE p.due_at >= $now AND p.due_at < $now + $w "
        "RETURN p.id, p.kind, p.due_at, u.id ORDER BY p.due_at",
        {"now": now, "w": within_s},
    ).result_set
