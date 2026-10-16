"""Derive: shortcut edges and signals, recomputed only for what one event touched (rules, not AI).

TOUCHES links a ticket straight to every hub, courier, batch and campaign its order went through,
so "who else is affected through this hub" is 2 hops instead of 6. It must hold whichever
arrives first, the ticket or the scan, so both event types run the same rule.
"""

from sinew.engine.writers import Ctx

# Ticket -> Order -> ... -> X, written as Ticket -TOUCHES-> X
_TOUCH_PATHS = {
    "Hub": "(t)-[:ABOUT]->(:Order)-[:SHIPPED_AS]->(:Shipment)<-[:FOR]-(:Scan)-[:AT]->(x:Hub)",
    "Courier": "(t)-[:ABOUT]->(:Order)-[:SHIPPED_AS]->(:Shipment)-[:VIA]->(x:Courier)",
    "Batch": "(t)-[:ABOUT]->(:Order)-[:HAS]->(:LineItem)-[:FROM]->(x:Batch)",
    "Campaign": "(t)-[:ABOUT]->(:Order)-[:USED]->(:Coupon)-[:OF]->(x:Campaign)",
}


def touches_for_ticket(c: Ctx, ticket_id: str):
    for label, path in _TOUCH_PATHS.items():
        c.g.query(
            f"MATCH (t:Ticket {{id: $t}}) MATCH {path} MERGE (t)-[:TOUCHES]->(x)",
            {"t": ticket_id},
        )


def touches_for_order(c: Ctx, order_id: str):
    rows = c.g.ro_query(
        "MATCH (t:Ticket)-[:ABOUT]->(:Order {id: $o}) RETURN t.id", {"o": order_id}
    ).result_set
    for (ticket_id,) in rows:
        touches_for_ticket(c, ticket_id)


def run(c: Ctx, event_type: str, p: dict) -> list[dict]:
    signals: list[dict] = []
    if event_type == "ticket.created":
        touches_for_ticket(c, p["ticket_id"])
        signals.append({"signal": "new_ticket", "ticket": p["ticket_id"]})
    elif event_type == "scan.recorded":
        rows = c.g.ro_query(
            "MATCH (:Shipment {id: $s})<-[:SHIPPED_AS]-(o:Order) RETURN o.id", {"s": p["shipment_id"]}
        ).result_set
        for (order_id,) in rows:
            touches_for_order(c, order_id)
        if (p.get("late_hours") or 0) > 0 or p["status"] == "delayed":
            signals.append({"signal": "late_scan", "shipment": p["shipment_id"], "hub": p["hub_id"]})
    elif event_type in ("order.placed", "shipment.created"):
        touches_for_order(c, p["order_id"])
    return signals
