"""Upsert: turn one clean event into graph writes.

Rules every writer follows (ENGINE.md §4):
- MERGE on ids, so the same event twice changes nothing.
- An update only applies if its source_updated_at is not older than what the node already has,
  so a late-arriving old event can never overwrite newer state.
- A link to a node that hasn't arrived yet creates a stub with just its id; the real event fills it later.
"""

from dataclasses import dataclass, field

from falkordb import Graph


@dataclass
class Ctx:
    g: Graph
    tenant: str
    event_id: str
    source: str
    occurred_at: int
    sua: int  # source_updated_at
    now: int
    identifiers: list[tuple[str, str]] = field(default_factory=list)  # (kind, hash)
    personal_fields: list[str] = field(default_factory=list)  # P0 field names that were dropped
    stale: bool = False


def upsert(c: Ctx, label: str, node_id: str, props: dict) -> bool:
    """Create or update one node; returns False when the update was older than what we hold."""
    rows = c.g.query(
        f"MERGE (n:{label} {{id: $id}}) ON CREATE SET n.recorded_at = $now "
        "WITH n WHERE coalesce(n.source_updated_at, -1) <= $sua "
        "SET n += $props, n.source_updated_at = $sua, n.source = $source "
        "RETURN count(n)",
        {"id": node_id, "now": c.now, "sua": c.sua, "props": props, "source": c.source},
    ).result_set
    applied = rows[0][0] == 1
    if not applied:
        c.stale = True
    return applied


def link(c: Ctx, a_label: str, a_id: str, rel: str, b_label: str, b_id: str, props: dict | None = None):
    c.g.query(
        f"MERGE (a:{a_label} {{id: $a}}) MERGE (b:{b_label} {{id: $b}}) "
        f"MERGE (a)-[r:{rel}]->(b) SET r += $props",
        {"a": a_id, "b": b_id, "props": props or {}},
    )


def personal_ref(c: Ctx, label: str, node_id: str):
    """Point at the source record that holds the personal fields; never copy them."""
    if c.personal_fields:
        ref_id = f"{c.source}:{label}:{node_id}"
        c.g.query(
            f"MERGE (n:{label} {{id: $id}}) MERGE (r:PersonalRef {{id: $ref}}) "
            "SET r.source = $source, r.record = $id, r.fields = $fields "
            "MERGE (n)-[:STORED_AT]->(r)",
            {"id": node_id, "ref": ref_id, "source": c.source, "fields": sorted(c.personal_fields)},
        )


# ---------------------------------------------------------------- staff and teams


def staff_upserted(c: Ctx, p: dict):
    upsert(c, "User", p["user_id"], {"role": p["role"], "refund_limit": p.get("refund_limit", 0)})
    link(c, "User", p["user_id"], "MEMBER_OF", "Team", p["team_id"])
    link(c, "User", p["user_id"], "HAS_ROLE", "Role", p["role"])
    if p.get("reports_to"):
        link(c, "User", p["user_id"], "REPORTS_TO", "User", p["reports_to"])
    personal_ref(c, "User", p["user_id"])


def team_upserted(c: Ctx, p: dict):
    upsert(c, "Team", p["team_id"], {"name": p["name"]})
    for region in p.get("covers_regions", []):
        link(c, "Team", p["team_id"], "COVERS", "Region", region)
    for queue in p.get("queues", []):
        link(c, "Team", p["team_id"], "WORKS", "Queue", queue)
    for category in p.get("owns_categories", []):
        link(c, "Team", p["team_id"], "OWNS", "Category", category)


# ---------------------------------------------------------------- catalogue and network


def supplier_upserted(c: Ctx, p: dict):
    upsert(c, "Supplier", p["supplier_id"], {})


def product_upserted(c: Ctx, p: dict):
    upsert(c, "Product", p["sku"], {"category": p["category"], "title": p.get("title", "")})
    link(c, "Product", p["sku"], "IN", "Category", p["category"])


def batch_upserted(c: Ctx, p: dict):
    upsert(c, "Batch", p["batch_id"], {"made_at": p.get("made_at", 0)})
    link(c, "Batch", p["batch_id"], "OF", "Product", p["sku"])
    link(c, "Batch", p["batch_id"], "MADE_BY", "Supplier", p["supplier_id"])


def courier_upserted(c: Ctx, p: dict):
    upsert(c, "Courier", p["courier_id"], {"name": p.get("name", p["courier_id"])})


def hub_upserted(c: Ctx, p: dict):
    upsert(c, "Hub", p["hub_id"], {"capacity": p.get("capacity", 0)})
    link(c, "Hub", p["hub_id"], "IN", "Region", p["region"])
    link(c, "Hub", p["hub_id"], "RUN_BY", "Courier", p["courier_id"])


def route_upserted(c: Ctx, p: dict):
    link(c, "Hub", p["from_hub"], "ROUTES_TO", "Hub", p["to_hub"],
         {"transit_h": p["transit_h"], "capacity": p.get("capacity", 0), "blocked": 0})


def warehouse_upserted(c: Ctx, p: dict):
    upsert(c, "Warehouse", p["warehouse_id"], {})
    link(c, "Warehouse", p["warehouse_id"], "IN", "Region", p["region"])


# ---------------------------------------------------------------- customers


def profile_upserted(c: Ctx, p: dict):
    upsert(c, "Profile", p["profile_id"], {
        "channel": p["channel"], "region": p["region"], "tier": p.get("tier", "standard"),
        "since": p.get("since", 0),
    })
    link(c, "Profile", p["profile_id"], "IN", "Region", p["region"])
    for kind, digest in c.identifiers:
        c.g.query(
            "MERGE (p:Profile {id: $p}) MERGE (i:Identifier {id: $h}) SET i.type = $kind, i.hash = $h "
            "MERGE (p)-[:HAS]->(i)",
            {"p": p["profile_id"], "h": digest, "kind": kind},
        )
    personal_ref(c, "Profile", p["profile_id"])


def consent_updated(c: Ctx, p: dict):
    if p["granted"]:
        link(c, "Profile", p["profile_id"], "CONSENTED", "Purpose", p["purpose"], {"at": c.occurred_at})
    else:
        c.g.query(
            "MATCH (:Profile {id: $p})-[r:CONSENTED]->(:Purpose {id: $u}) DELETE r",
            {"p": p["profile_id"], "u": p["purpose"]},
        )


# ---------------------------------------------------------------- commerce


def order_placed(c: Ctx, p: dict):
    # Properties apply only if newer; the links below are structural facts and are always written.
    upsert(c, "Order", p["order_id"], {
        "placed_at": p["placed_at"], "status": p["status"], "currency": p["currency"], "total": p["total"],
    })
    link(c, "Profile", p["profile_id"], "PLACED", "Order", p["order_id"])
    if p.get("warehouse_id"):
        link(c, "Order", p["order_id"], "FROM", "Warehouse", p["warehouse_id"])
    if p.get("coupon_code"):
        link(c, "Order", p["order_id"], "USED", "Coupon", p["coupon_code"])
    for line in p["lines"]:
        c.g.query(
            "MERGE (o:Order {id: $o}) MERGE (l:LineItem {id: $l}) SET l.qty = $qty, l.price = $price "
            "MERGE (o)-[:HAS]->(l) "
            "MERGE (pr:Product {id: $sku}) MERGE (l)-[:OF]->(pr) "
            "WITH l WHERE $batch IS NOT NULL MERGE (b:Batch {id: $batch}) MERGE (l)-[:FROM]->(b)",
            {"o": p["order_id"], "l": line["line_id"], "qty": line["qty"], "price": line["price"],
             "sku": line["sku"], "batch": line.get("batch_id")},
        )
    personal_ref(c, "Order", p["order_id"])


def order_updated(c: Ctx, p: dict):
    upsert(c, "Order", p["order_id"], {"status": p["status"]})


def payment_captured(c: Ctx, p: dict):
    upsert(c, "Payment", p["payment_id"], {"method": p["method"], "amount": p["amount"], "at": c.occurred_at})
    link(c, "Order", p["order_id"], "PAID_BY", "Payment", p["payment_id"])


def refund_issued(c: Ctx, p: dict):
    upsert(c, "Refund", p["refund_id"], {"amount": p["amount"], "status": p["status"], "at": c.occurred_at})
    link(c, "Refund", p["refund_id"], "FOR", "Order", p["order_id"])
    if p.get("approved_by"):
        link(c, "Refund", p["refund_id"], "APPROVED_BY", "User", p["approved_by"])


def return_created(c: Ctx, p: dict):
    upsert(c, "Return", p["return_id"], {"reason": p.get("reason", ""), "status": p["status"], "at": c.occurred_at})
    link(c, "Return", p["return_id"], "OF", "LineItem", p["line_id"])


# ---------------------------------------------------------------- delivery


def shipment_created(c: Ctx, p: dict):
    upsert(c, "Shipment", p["shipment_id"], {"promised_at": p["promised_at"], "status": "created"})
    link(c, "Order", p["order_id"], "SHIPPED_AS", "Shipment", p["shipment_id"])
    link(c, "Shipment", p["shipment_id"], "VIA", "Courier", p["courier_id"])


def scan_recorded(c: Ctx, p: dict):
    # The scan is an event node (decision 1): tickets and evidence can point at it.
    upsert(c, "Scan", p["scan_id"], {"at": c.occurred_at, "status": p["status"],
                                     "late_hours": p.get("late_hours", 0)})
    link(c, "Scan", p["scan_id"], "FOR", "Shipment", p["shipment_id"])
    link(c, "Scan", p["scan_id"], "AT", "Hub", p["hub_id"])
    # Current state lives on the entity too, but only if this scan is the newest one we've seen.
    c.g.query(
        "MATCH (s:Shipment {id: $s}) WHERE coalesce(s.last_scan_at, -1) <= $at "
        "SET s.status = $status, s.last_scan_at = $at, s.last_hub = $hub, "
        "    s.late_hours = coalesce($late, 0)",
        {"s": p["shipment_id"], "at": c.occurred_at, "status": p["status"], "hub": p["hub_id"],
         "late": p.get("late_hours")},
    )


# ---------------------------------------------------------------- support


def ticket_created(c: Ctx, p: dict):
    upsert(c, "Ticket", p["ticket_id"], {
        "at": c.occurred_at, "channel": p["channel"], "status": "open",
        "summary_clean": p["text"], "issue_type": p.get("issue_type", "other"),
    })
    link(c, "Ticket", p["ticket_id"], "FROM", "Profile", p["profile_id"])
    link(c, "Ticket", p["ticket_id"], "IN", "Queue", p["queue_id"])
    if p.get("issue_type"):
        link(c, "Ticket", p["ticket_id"], "IS", "IssueType", p["issue_type"])
    if p.get("order_id"):
        link(c, "Ticket", p["ticket_id"], "ABOUT", "Order", p["order_id"])
    if p.get("handled_by"):
        link(c, "Ticket", p["ticket_id"], "HANDLED_BY", "User", p["handled_by"])


def ticket_updated(c: Ctx, p: dict):
    upsert(c, "Ticket", p["ticket_id"], {"status": p["status"]})
    if p.get("handled_by"):
        link(c, "Ticket", p["ticket_id"], "HANDLED_BY", "User", p["handled_by"])


# ---------------------------------------------------------------- marketing


def campaign_upserted(c: Ctx, p: dict):
    upsert(c, "Campaign", p["campaign_id"], {
        "name": p["name"], "starts": p["starts"], "ends": p["ends"], "status": p["status"],
        "category": p.get("category", ""),
    })
    link(c, "Campaign", p["campaign_id"], "TARGETS", "Region", p["region"])
    if p.get("category"):
        link(c, "Campaign", p["campaign_id"], "FOR", "Category", p["category"])
    if p.get("owner"):
        link(c, "Campaign", p["campaign_id"], "OWNED_BY", "User", p["owner"])
    for code in p.get("coupon_codes", []):
        link(c, "Coupon", code, "OF", "Campaign", p["campaign_id"])


# ---------------------------------------------------------------- decisions

CHOOSABLE = {"Courier", "Hub", "Supplier", "Warehouse", "Campaign"}


def decision_recorded(c: Ctx, p: dict):
    upsert(c, "Decision", p["decision_id"], {
        "title": p["title"], "made_at": p["made_at"], "status": p.get("status", "active"),
        "chose_kind": p["chose_kind"],
    })
    link(c, "Decision", p["decision_id"], "OWNED_BY", "User", p["owner"])
    link(c, "Decision", p["decision_id"], "CHOSE", p["chose_kind"], p["chose_id"])
    if p.get("region"):
        link(c, "Decision", p["decision_id"], "FOR", "Region", p["region"])
    for earlier in p.get("builds_on", []):
        link(c, "Decision", p["decision_id"], "BUILDS_ON", "Decision", earlier)
    if p.get("doc_id"):
        link(c, "Decision", p["decision_id"], "RECORDED_IN", "Doc", p["doc_id"])
    for a in p["assumptions"]:
        c.g.query(
            "MERGE (d:Decision {id: $d}) MERGE (a:Assumption {id: $a}) "
            "SET a.statement = $statement, a.metric = $metric, a.op = $op, a.threshold = $threshold, "
            "    a.window_days = $window, a.scope_hub = $hub, a.scope_courier = $courier, "
            "    a.status = coalesce(a.status, 'unchecked') "
            "MERGE (d)-[:RESTS_ON]->(a)",
            {"d": p["decision_id"], "a": a["assumption_id"], "statement": a["statement"],
             "metric": a["metric"], "op": a["op"], "threshold": a["threshold"], "window": a["window_days"],
             "hub": a.get("scope_hub"), "courier": a.get("scope_courier")},
        )
        if a.get("scope_hub"):
            link(c, "Assumption", a["assumption_id"], "ABOUT", "Hub", a["scope_hub"])
        if a.get("scope_courier"):
            link(c, "Assumption", a["assumption_id"], "ABOUT", "Courier", a["scope_courier"])


# ---------------------------------------------------------------- promises


def promise_proposed(c: Ctx, p: dict):
    upsert(c, "Promise", p["promise_id"], {
        "kind": p["kind"], "due_at": p["due_at"], "amount": p.get("amount", 0), "made_at": c.occurred_at,
    })
    c.g.query("MATCH (p:Promise {id: $id}) WHERE p.status IS NULL SET p.status = 'proposed'",
              {"id": p["promise_id"]})
    link(c, "Promise", p["promise_id"], "MADE_IN", "Ticket", p["ticket_id"])
    link(c, "Promise", p["promise_id"], "CONCERNS", "Order", p["order_id"])
    link(c, "Promise", p["promise_id"], "MADE_BY", "User", p["made_by"])


def promise_confirmed(c: Ctx, p: dict):
    c.g.query(
        "MATCH (p:Promise {id: $id}) WHERE p.status = 'proposed' SET p.status = 'open', p.confirmed_by = $by",
        {"id": p["promise_id"], "by": p["confirmed_by"]},
    )


def promise_rejected(c: Ctx, p: dict):
    c.g.query(
        "MATCH (p:Promise {id: $id}) WHERE p.status = 'proposed' SET p.status = 'rejected', p.rejected_by = $by",
        {"id": p["promise_id"], "by": p["rejected_by"]},
    )


WRITERS = {
    "staff.upserted": staff_upserted, "team.upserted": team_upserted,
    "supplier.upserted": supplier_upserted, "product.upserted": product_upserted,
    "batch.upserted": batch_upserted, "courier.upserted": courier_upserted,
    "hub.upserted": hub_upserted, "route.upserted": route_upserted,
    "warehouse.upserted": warehouse_upserted,
    "profile.upserted": profile_upserted, "consent.updated": consent_updated,
    "order.placed": order_placed, "order.updated": order_updated,
    "payment.captured": payment_captured, "refund.issued": refund_issued, "return.created": return_created,
    "shipment.created": shipment_created, "scan.recorded": scan_recorded,
    "ticket.created": ticket_created, "ticket.updated": ticket_updated,
    "campaign.upserted": campaign_upserted, "decision.recorded": decision_recorded,
    "promise.proposed": promise_proposed, "promise.confirmed": promise_confirmed,
    "promise.rejected": promise_rejected,
}
