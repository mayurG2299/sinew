"""Entity-anchored retrieval: start at the node the question names and walk only the relationships it needs.

    order_detail     (Order)-[:PAID_BY|HAS|SHIPPED_AS|USED]-> ... <-[:FOR|ABOUT|CONCERNS]-(Refund|Ticket|Promise)
    decision_detail  (Decision)-[:RESTS_ON]->(Assumption)<-[:TESTS]-(Evidence), -[:AFFECTS]->(Hub),
                     -[:BUILDS_ON]-(Decision), <-[:BREAKS]-(Decision)
    hub_status       (Hub)-[:RUN_BY]->(Courier), <-[:AT]-(Scan), <-[:AFFECTS]-(Decision), parcels whose last hub it is

Each returns a few hundred characters of exactly the facts asked about, with dates already readable, so the
model only writes the sentence. Permission follows the same path as everywhere else: an order is reachable only
through its customer (guard.customer_access); decisions and hubs need the operations area.
"""

import re
import time

from sinew.db import graph
from sinew.tools import guard
from sinew.tools.answer import Answer, refused, unknown
from sinew.tools.trace import clock, resolve_customer

DAY = 86_400


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _when(at: int | None) -> str | None:
    return time.strftime("%-d %b, %H:%M", time.gmtime(at)) if at else None


def _order_id(ref: str) -> str | None:
    m = re.fullmatch(r"(?:order\s*)?#?\s*o?-?(\d{3,6})", ref.strip(), re.I)
    return f"o-{m.group(1)}" if m else None


def order_detail(tenant: str, user_id: str, order: str) -> Answer:
    start = time.perf_counter()
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return unknown("order_detail", f"user {user_id}")
    oid = _order_id(order)
    g = graph(tenant)
    if not oid or not g.ro_query("MATCH (o:Order {id: $o}) RETURN o.id", {"o": oid}).result_set:
        return unknown("order_detail", f"order {order}")
    customer = resolve_customer(tenant, oid)
    allowed, reason, grant = guard.customer_access(v, customer)
    if not allowed:
        guard.record_access(v, "order_detail:refused", customer)
        return refused("order_detail", reason)

    head = g.ro_query(
        "MATCH (o:Order {id: $o}) OPTIONAL MATCH (o)-[:USED]->(k:Coupon) "
        "OPTIONAL MATCH (o)-[:HAS]->(l:LineItem)-[:OF]->(p:Product) "
        "RETURN o.placed_at, o.status, o.total, o.currency, k.id, collect({item: p.title, qty: l.qty, price: l.price})",
        {"o": oid}).result_set[0]
    placed, status, total, currency, coupon, items = head
    pay = g.ro_query("MATCH (:Order {id: $o})-[:PAID_BY]->(p:Payment) RETURN p.method, p.amount, p.at", {"o": oid}).result_set
    ship = g.ro_query(
        "MATCH (:Order {id: $o})-[:SHIPPED_AS]->(s:Shipment) OPTIONAL MATCH (s)-[:VIA]->(c:Courier) "
        "RETURN s.status, s.promised_at, s.late_hours, c.id", {"o": oid}).result_set
    scans = g.ro_query(
        "MATCH (:Order {id: $o})-[:SHIPPED_AS]->(:Shipment)<-[:FOR]-(sc:Scan)-[:AT]->(h:Hub) "
        "RETURN sc.at, h.id, sc.status, sc.late_hours ORDER BY sc.at", {"o": oid}).result_set
    refunds = g.ro_query("MATCH (:Order {id: $o})<-[:FOR]-(r:Refund) RETURN r.amount, r.status, r.at", {"o": oid}).result_set
    tickets = g.ro_query(
        "MATCH (:Order {id: $o})<-[:ABOUT]-(t:Ticket) RETURN t.at, t.issue_type, t.status, t.channel, t.summary_clean "
        "ORDER BY t.at", {"o": oid}).result_set
    commitments = g.ro_query("MATCH (:Order {id: $o})<-[:CONCERNS]-(p:Promise) RETURN p.kind, p.due_at, p.status, p.amount",
                             {"o": oid}).result_set
    customer_orders = g.ro_query("MATCH (:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order) RETURN count(o)",
                                 {"c": customer}).result_set[0][0]
    now = clock(tenant)
    delivered = next((at for at, _, st, _ in scans if st == "delivered"), None)
    data = {
        "order": "#" + oid[2:], "placed": _when(placed), "customer_orders_in_total": customer_orders, "total": total, "currency": currency,
        "coupon": coupon.upper() if coupon else None, "items": [i for i in items if i["item"]],
        "delivery": {
            "delivered": bool(delivered), "delivered_on": _when(delivered),
            "status": "delivered" if delivered else (ship[0][0].replace("_", " ") if ship and ship[0][0] else "not shipped yet"),
            "courier": ship[0][3] if ship else None,
            "promised_by": _when(ship[0][1]) if ship else None,
            "late_hours": ship[0][2] if ship and not delivered else 0,
            "scans": [{"when": _when(at), "hub": h, "status": st.replace("_", " "), "late_hours": lh or 0}
                      for at, h, st, lh in scans],
        },
        "refunds": [{"amount": a, "status": s, "when": _when(at)} for a, s, at in refunds],
        "refunded_total": round(sum(a for a, s, _ in refunds if s == "issued"), 2),
        "tickets": [{"opened": _when(at), "issue": (i or "").replace("_", " "), "status": s, "channel": c, "summary": t}
                    for at, i, s, c, t in tickets],
        "commitments": [{"kind": k, "due": _when(d), "status": s.replace("_", " "),
                         "overdue": s == "broken" or (s == "open" and d < now), "amount": a or None}
                        for k, d, s, a in commitments],
    }
    hidden = []
    if "payment" in guard.HIDDEN_FOR.get(v.role, {}):
        hidden.append({"kind": "payment", "count": len(pay), "reason": guard.HIDDEN_FOR[v.role]["payment"]})
    else:
        data["payment"] = [{"method": "cash on delivery" if m == "cod" else m, "amount": a, "when": _when(at)} for m, a, at in pay]
    guard.record_access(v, "order_detail", customer)
    return Answer("order_detail", "answered_path", data=data, hidden=hidden, ms=_ms(start),
                  paths=[grant + [oid]] + [[oid, h] for _, h, _, _ in scans])


def _find_decision(tenant: str, ref: str) -> str | None:
    """A decision by id, or by the words of its title (best overlap)."""
    rows = graph(tenant).ro_query("MATCH (d:Decision) RETURN d.id, d.title").result_set
    ref_l = ref.strip().lower()
    for did, title in rows:
        if ref_l in (did, title.lower()):
            return did
    words = set(re.findall(r"[a-z0-9]{3,}", ref_l)) - {"the", "and", "decision", "run", "west", "region"}
    best = max(((len(words & set(re.findall(r"[a-z0-9]{3,}", t.lower()))), d) for d, t in rows), default=(0, None))
    return best[1] if best[0] >= 1 else None


def decision_detail(tenant: str, user_id: str, decision: str) -> Answer:
    start = time.perf_counter()
    did = _find_decision(tenant, decision)
    if did is None:
        return unknown("decision_detail", f"decision {decision!r}")
    g = graph(tenant)
    head = g.ro_query(
        "MATCH (d:Decision {id: $d}) OPTIONAL MATCH (d)-[:OWNED_BY]->(u:User) "
        "OPTIONAL MATCH (d)-[:AFFECTS]->(h:Hub) RETURN d.title, d.made_at, d.chose_kind, u.id, collect(DISTINCT h.id)",
        {"d": did}).result_set[0]
    title, made, kind, owner, hubs = head
    assumptions = g.ro_query(
        "MATCH (:Decision {id: $d})-[:RESTS_ON]->(a:Assumption) OPTIONAL MATCH (e:Evidence)-[:TESTS]->(a) "
        "WITH a, e ORDER BY e.window_end DESC WITH a, collect(e)[0] AS latest "
        "OPTIONAL MATCH (other:Decision)-[b:BREAKS]->(a) "
        "RETURN a.statement, a.metric, a.op, a.threshold, a.status, latest.value, latest.sample, other.title, b.basis",
        {"d": did}).result_set
    builds_on = [t for t, in g.ro_query("MATCH (:Decision {id: $d})-[:BUILDS_ON]->(x:Decision) RETURN x.title", {"d": did}).result_set]
    relied_on_by = [t for t, in g.ro_query("MATCH (x:Decision)-[:BUILDS_ON*1..3]->(:Decision {id: $d}) RETURN DISTINCT x.title",
                                          {"d": did}).result_set]
    campaign = g.ro_query("MATCH (:Decision {id: $d})-[:CHOSE]->(c:Campaign) RETURN c.name, c.status, c.starts, c.ends",
                          {"d": did}).result_set
    now = clock(tenant)
    show = lambda m, v: None if v is None else (f"{round(v * 100)}%" if m == "courier_on_time_rate" else f"{v:.2f}x capacity")
    data = {
        "decision": title, "made": _when(made), "owner": owner, "chose": kind, "hubs": hubs,
        "assumptions": [{"assumed": s, "needs": f"{'at least' if op == '>=' else 'at most'} {show(m, t)}",
                         "now": show(m, val), "holds": st != "broken", "measured_on": f"{int(n)} scans" if n else None,
                         "overlaps_with": o, "overlap": basis} for s, m, op, t, st, val, n, o, basis in assumptions],
        "builds_on": builds_on, "decisions_relying_on_it": relied_on_by,
    }
    if campaign:
        name, cstatus, starts, ends = campaign[0]
        coupon_orders = g.ro_query("MATCH (:Decision {id: $d})-[:CHOSE]->(c:Campaign)<-[:OF]-(:Coupon)<-[:USED]-(o:Order) "
                                   "RETURN count(DISTINCT o)", {"d": did}).result_set[0][0]
        data["campaign"] = {"name": name, "status": cstatus,
                            "starts_in_days": round((starts - now) / DAY) if starts > now else None,
                            "ends_in_days": round((ends - now) / DAY) if ends > now else None,
                            "coupon_orders_so_far": coupon_orders}
    return Answer("decision_detail", "answered_path", data=data, ms=_ms(start),
                  paths=[[did, h] for h in hubs] + [[did, "RESTS_ON", s] for s, *_ in assumptions])


def hub_status(tenant: str, user_id: str, hub: str) -> Answer:
    start = time.perf_counter()
    m = re.search(r"([a-z])\s*-?\s*(\d+)", hub.lower().replace("hub", ""))
    hid = f"hub-{m.group(1)}{m.group(2)}" if m else hub.strip().lower()
    g = graph(tenant)
    head = g.ro_query("MATCH (h:Hub {id: $h}) OPTIONAL MATCH (h)-[:RUN_BY]->(c:Courier) RETURN h.capacity, c.id",
                      {"h": hid}).result_set
    if not head:
        return unknown("hub_status", f"hub {hub}")
    capacity, courier = head[0]
    now = clock(tenant)
    w = {"h": hid, "s": now - 7 * DAY, "e": now}
    waiting, late, people = g.ro_query(
        "MATCH (s:Shipment {last_hub: $h}) WHERE s.status IN ['in_transit', 'delayed'] "
        "OPTIONAL MATCH (s)<-[:SHIPPED_AS]-(:Order)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) "
        "RETURN count(DISTINCT s), count(DISTINCT CASE WHEN s.late_hours > 0 THEN s END), count(DISTINCT c)", w).result_set[0]
    scans, on_time, busiest = g.ro_query(
        "MATCH (sc:Scan)-[:AT]->(:Hub {id: $h}) WHERE sc.at >= $s AND sc.at < $e AND sc.status IN ['in_transit', 'delayed'] "
        "WITH sc, sc.at / 86400 AS day WITH count(sc) AS n, sum(CASE WHEN coalesce(sc.late_hours, 0) = 0 THEN 1 ELSE 0 END) AS ok, "
        "collect(day) AS days RETURN n, ok, days", w).result_set[0]
    per_day = {}
    for d in busiest:
        per_day[d] = per_day.get(d, 0) + 1
    decisions = g.ro_query(
        "MATCH (d:Decision)-[:AFFECTS]->(:Hub {id: $h}) OPTIONAL MATCH (d)-[:RESTS_ON]->(a:Assumption {status: 'broken'}) "
        "RETURN d.title, count(a) > 0", w).result_set
    data = {"hub": hid.replace("hub-", "Hub ").upper().replace("HUB ", "Hub "), "run_by": courier,
            "capacity_per_day": capacity, "parcels_there_now": waiting, "customers_waiting": people, "late_now": int(late or 0),
            "on_time_this_week": f"{round(on_time / scans * 100)}%" if scans else None,
            "busiest_day_parcels": max(per_day.values()) if per_day else 0,
            "decisions": [{"decision": t, "assumption_broken": b} for t, b in decisions]}
    return Answer("hub_status", "answered_path", data=data, ms=_ms(start), paths=[[hid, courier]])


def product_status(tenant: str, user_id: str, item: str, days: int = 30) -> Answer:
    """A product or a batch, walked to the orders that contain it and the complaints and returns on those orders:
    (Product|Batch)<-[:OF|FROM]-(LineItem)<-[:HAS]-(Order)<-[:ABOUT]-(Ticket), (LineItem)<-[:OF]-(Return)."""
    start = time.perf_counter()
    g = graph(tenant)
    ref = item.strip().lower()
    ref = re.sub(r"^batch\s+", "", ref)
    found = g.ro_query("MATCH (b:Batch) WHERE toLower(b.id) = $r RETURN 'Batch' AS kind, b.id AS id, b.id AS label",
                       {"r": ref}).result_set or \
        g.ro_query("MATCH (p:Product) WHERE toLower(p.title) = $r OR p.id = $r RETURN 'Product', p.id, p.title", {"r": ref}).result_set
    if not found:
        return unknown("product_status", f"product or batch {item!r}")
    kind, nid, label = found[0]
    rel = "(l:LineItem)-[:FROM]->(:Batch {id: $x})" if kind == "Batch" else "(l:LineItem)-[:OF]->(:Product {id: $x})"
    now = clock(tenant)
    w = {"x": nid, "s": now - days * DAY}
    orders = g.ro_query(f"MATCH {rel} MATCH (o:Order)-[:HAS]->(l) WHERE o.placed_at >= $s RETURN count(DISTINCT o)", w).result_set[0][0]
    issues = g.ro_query(f"MATCH {rel} MATCH (o:Order)-[:HAS]->(l) WHERE o.placed_at >= $s "
                        "MATCH (t:Ticket)-[:ABOUT]->(o) RETURN t.issue_type, count(DISTINCT t) ORDER BY count(DISTINCT t) DESC", w).result_set
    returns = g.ro_query(f"MATCH {rel} MATCH (o:Order)-[:HAS]->(l) WHERE o.placed_at >= $s "
                         "MATCH (r:Return)-[:OF]->(l) RETURN count(DISTINCT r)", w).result_set[0][0]
    complaints = sum(n for _, n in issues)
    all_orders = g.ro_query("MATCH (o:Order) WHERE o.placed_at >= $s RETURN count(o)", w).result_set[0][0]
    all_tickets = g.ro_query("MATCH (o:Order) WHERE o.placed_at >= $s MATCH (t:Ticket)-[:ABOUT]->(o) RETURN count(DISTINCT t)",
                             w).result_set[0][0]
    product_kinds = {"product_issue", "damaged", "wrong_item"}
    quality = sum(n for i, n in issues if i in product_kinds)
    data = {"item": label if kind == "Product" else f"Batch {nid.upper()}", "kind": kind.lower(), "days": days,
            "orders": orders, "complaints": complaints, "quality_complaints": quality, "returns": returns,
            "complaints_per_100_orders": f"{complaints / orders * 100:.1f} per 100 orders" if orders else None,
            "baseline_complaints_per_100_orders": f"{all_tickets / all_orders * 100:.1f} per 100 orders (all products)" if all_orders else None,
            "by_issue": [{"issue": (i or "other").replace("_", " "), "tickets": n} for i, n in issues]}
    if kind == "Batch":
        sup = g.ro_query("MATCH (:Batch {id: $x}) OPTIONAL MATCH (b:Batch {id: $x})-[:FROM|MADE_BY|SUPPLIED_BY]->(s) "
                         "OPTIONAL MATCH (b)-[:OF]->(p:Product) RETURN s.id, p.title", w).result_set
        if sup:
            data["supplier"], data["product"] = sup[0]
    return Answer("product_status", "answered_path", data=data, ms=_ms(start), paths=[[nid, "orders", "tickets"]])
