"""Customer trace tools (Hero 1): resolve, complete trace, open loops, related issues.

All reads use ro_query. Every entity is resolved against the graph before anything else runs.
"""

import time

from sinew.db import graph
from sinew.engine.minimise import keyed_hash, normalise
from sinew.tools import guard
from sinew.tools.answer import Answer, refused, unknown

DAY = 86_400


def clock(tenant: str) -> int:
    rows = graph(tenant).ro_query("MATCH (m:Meta {id: 'clock'}) RETURN m.now").result_set
    return rows[0][0] if rows else int(time.time())


# ------------------------------------------------------------------ resolve


def resolve_customer(tenant: str, ref: str) -> str | None:
    """A customer id, a profile id, an order id, a ticket id, or a raw email/phone (hashed, never stored)."""
    g = graph(tenant)
    queries = [
        ("MATCH (c:Customer {id: $r}) RETURN c.id", ref),
        ("MATCH (:Profile {id: $r})-[:OF]->(c:Customer) RETURN c.id", ref),
        ("MATCH (:Order {id: $r})<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) RETURN c.id", ref),
        ("MATCH (:Ticket {id: $r})-[:FROM]->(:Profile)-[:OF]->(c:Customer) RETURN c.id", ref),
    ]
    kind = "email" if "@" in ref else "phone" if any(ch.isdigit() for ch in ref) and len(ref) >= 7 else None
    if kind:
        norm = normalise(kind, ref)
        if norm:
            queries.append(("MATCH (:Identifier {id: $r})<-[:HAS]-(:Profile)-[:OF]->(c:Customer) RETURN c.id",
                            keyed_hash(tenant, kind, norm)))
    for q, param in queries:
        rows = g.ro_query(q, {"r": param}).result_set
        if rows:
            return rows[0][0]
    return None


def resolve(tenant: str, label: str, node_id: str) -> bool:
    return bool(graph(tenant).ro_query(f"MATCH (n:{label} {{id: $id}}) RETURN n.id", {"id": node_id}).result_set)


# ------------------------------------------------------------------ trace


def customer_trace(tenant: str, user_id: str, ref: str) -> Answer:
    start = time.perf_counter()
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return unknown("customer_trace", f"user {user_id}")
    customer = resolve_customer(tenant, ref)
    if customer is None:
        return unknown("customer_trace", f"customer {ref!r}")
    allowed, reason, grant = guard.customer_access(v, customer)
    if not allowed:
        guard.record_access(v, "customer_trace:refused", customer)
        return refused("customer_trace", reason)
    g = graph(tenant)
    items: list[dict] = []
    paths: list[list[str]] = [grant]

    head = g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(p:Profile) RETURN c.region, c.tier, c.since, collect(p.id), "
        "collect(p.channel)", {"c": customer}).result_set[0]
    region, tier, since, profile_ids, channels = head

    for oid, placed, status, total, cur, coupon, lines, pid in g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(p:Profile)-[:PLACED]->(o:Order) "
        "OPTIONAL MATCH (o)-[:USED]->(k:Coupon) "
        "OPTIONAL MATCH (o)-[:HAS]->(l:LineItem)-[:OF]->(pr:Product) OPTIONAL MATCH (l)-[:FROM]->(b:Batch) "
        "RETURN o.id, o.placed_at, o.status, o.total, o.currency, k.id, "
        "collect({sku: pr.id, title: pr.title, batch: b.id, price: l.price}), p.id",
        {"c": customer}).result_set:
        items.append({"at": placed, "kind": "order", "id": oid, "status": status, "total": total, "currency": cur,
                      "coupon": coupon, "lines": lines})
        paths.append([customer, pid, oid])

    for oid, pay, method, amount, at in g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)-[:PAID_BY]->(pay:Payment) "
        "RETURN o.id, pay.id, pay.method, pay.amount, pay.at", {"c": customer}).result_set:
        items.append({"at": at, "kind": "payment", "id": pay, "order": oid, "method": method, "amount": amount})

    for oid, sid, courier, promised, scans in g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)-[:SHIPPED_AS]->(s:Shipment) "
        "OPTIONAL MATCH (s)-[:VIA]->(k:Courier) "
        "OPTIONAL MATCH (sc:Scan)-[:FOR]->(s) OPTIONAL MATCH (sc)-[:AT]->(h:Hub) "
        "WITH o, s, k, sc, h ORDER BY sc.at "
        "RETURN o.id, s.id, k.id, s.promised_at, collect({at: sc.at, hub: h.id, status: sc.status, "
        "late_hours: sc.late_hours})", {"c": customer}).result_set:
        scans = [x for x in scans if x["at"] is not None]
        for x in scans:
            items.append({"at": x["at"], "kind": "scan", "id": sid, "order": oid, "courier": courier,
                          "hub": x["hub"], "status": x["status"], "late_hours": x["late_hours"]})
            paths.append([customer, oid, sid, x["hub"]])

    for oid, rid, amount, status, at, approver in g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)<-[:FOR]-(r:Refund) "
        "OPTIONAL MATCH (r)-[:APPROVED_BY]->(u:User) RETURN o.id, r.id, r.amount, r.status, r.at, u.id",
        {"c": customer}).result_set:
        items.append({"at": at, "kind": "refund", "id": rid, "order": oid, "amount": amount, "status": status,
                      "approved_by": approver})

    for oid, rt, reason_, status, at in g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)-[:HAS]->(:LineItem)<-[:OF]-(r:Return) "
        "RETURN o.id, r.id, r.reason, r.status, r.at", {"c": customer}).result_set:
        items.append({"at": at, "kind": "return", "id": rt, "order": oid, "reason": reason_, "status": status})

    for tid, at, channel, status, issue, summary, oid, handler, pid in g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(p:Profile)<-[:FROM]-(t:Ticket) "
        "OPTIONAL MATCH (t)-[:ABOUT]->(o:Order) OPTIONAL MATCH (t)-[:HANDLED_BY]->(u:User) "
        "RETURN t.id, t.at, t.channel, t.status, t.issue_type, t.summary_clean, o.id, u.id, p.id",
        {"c": customer}).result_set:
        items.append({"at": at, "kind": "ticket", "id": tid, "channel": channel, "status": status, "issue": issue,
                      "summary": summary, "order": oid, "handled_by": handler})
        paths.append([customer, pid, tid] + ([oid] if oid else []))

    for prid, kind, due, status, made, oid, tid, by, kept_by in g.ro_query(
        "MATCH (c:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)<-[:CONCERNS]-(pr:Promise) "
        "OPTIONAL MATCH (pr)-[:MADE_IN]->(t:Ticket) OPTIONAL MATCH (pr)-[:MADE_BY]->(u:User) "
        "OPTIONAL MATCH (pr)-[:KEPT_BY]->(a) "
        "RETURN pr.id, pr.kind, pr.due_at, pr.status, pr.made_at, o.id, t.id, u.id, a.id",
        {"c": customer}).result_set:
        items.append({"at": made, "kind": "promise", "id": prid, "promise": kind, "due_at": due, "status": status,
                      "order": oid, "ticket": tid, "made_by": by, "kept_by": kept_by})

    hidden = []
    for kind, why in guard.HIDDEN_FOR.get(v.role, {}).items():
        n = sum(1 for i in items if i["kind"] == kind)
        if n:
            hidden.append({"kind": kind, "count": n, "reason": why})
    items = [i for i in items if i["kind"] not in guard.HIDDEN_FOR.get(v.role, {})]
    items.sort(key=lambda i: (i["at"] or 0, i["kind"]))

    personal, personal_hidden = guard.fetch_personal(v, customer)
    guard.record_access(v, "customer_trace", customer)
    return Answer(
        "customer_trace", "answered_path",
        data={"customer": customer, "region": region, "tier": tier, "since": since,
              "channels": sorted(set(channels)), "profiles": profile_ids, "personal": personal,
              "granted_by": reason, "timeline": items},
        paths=paths, hidden=hidden + personal_hidden, ms=round((time.perf_counter() - start) * 1000, 1))


def open_loops(tenant: str, user_id: str, ref: str) -> Answer:
    trace = customer_trace(tenant, user_id, ref)
    if trace.outcome != "answered_path":
        trace.tool = "open_loops"
        return trace
    now = clock(tenant)
    t = trace.data["timeline"]
    latest_scan = {}
    for i in t:
        if i["kind"] == "scan":
            latest_scan[i["id"]] = i
    refunded = {i["order"] for i in t if i["kind"] == "refund" and i["status"] == "issued"}
    loops = {
        "open_tickets": [i for i in t if i["kind"] == "ticket" and i["status"] != "solved"],
        "broken_promises": [i for i in t if i["kind"] == "promise" and i["status"] == "broken"],
        "open_promises": [i for i in t if i["kind"] == "promise" and i["status"] in ("open", "proposed")],
        "late_in_transit": [s for s in latest_scan.values() if s["status"] in ("delayed", "in_transit")
                            and (s["late_hours"] or 0) > 0],
        "returns_not_refunded": [i for i in t if i["kind"] == "return" and i["order"] not in refunded],
    }
    return Answer("open_loops", "answered_path" if any(loops.values()) else "not_in_graph",
                  data={"customer": trace.data["customer"], "as_of": now, **loops}, paths=trace.paths,
                  hidden=trace.hidden, ms=trace.ms,
                  reason="" if any(loops.values()) else "no open tickets, promises, late parcels or pending returns")


def related_issues(tenant: str, user_id: str, ticket_id: str, days: int = 7) -> Answer:
    """Other recent tickets through the same hub, courier, batch or campaign (2 hops via TOUCHES)."""
    start = time.perf_counter()
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return unknown("related_issues", f"user {user_id}")
    if not resolve(tenant, "Ticket", ticket_id):
        return unknown("related_issues", f"ticket {ticket_id}")
    now = clock(tenant)
    rows = graph(tenant).ro_query(
        "MATCH (t:Ticket {id: $t})-[:TOUCHES]->(x)<-[:TOUCHES]-(other:Ticket) "
        "WHERE other.at >= $since AND other <> t "
        "RETURN labels(x)[0], x.id, count(other), "
        "sum(CASE WHEN other.issue_type = t.issue_type THEN 1 ELSE 0 END) ORDER BY count(other) DESC",
        {"t": ticket_id, "since": now - days * DAY}).result_set
    if not rows:
        return Answer("related_issues", "not_in_graph", reason=f"no other tickets in {days} days share a hub, "
                      "courier, batch or campaign with this one", ms=round((time.perf_counter() - start) * 1000, 1))
    data = [{"through": label, "id": xid, "other_tickets": n, "same_issue": same} for label, xid, n, same in rows]
    return Answer("related_issues", "answered_path", data={"ticket": ticket_id, "days": days, "shared": data},
                  paths=[[ticket_id, d["id"], f"{d['other_tickets']} other tickets"] for d in data],
                  ms=round((time.perf_counter() - start) * 1000, 1))
