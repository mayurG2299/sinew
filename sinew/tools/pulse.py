"""Company pulse: the state of the company this week, built only from the areas this person's role can read.

Sections, one per area (support, operations, marketing, finance). A section the role can't read is never
computed, so no figure from it can reach the AI; the answer says which areas were left out, nothing more.
All changes and ratios are computed here, so the AI never has to do arithmetic (and the sentence check can
verify every number). Empty weeks give None, never a division by zero.
"""

import time

from sinew.db import graph
from sinew.tools import guard
from sinew.tools.answer import Answer, unknown
from sinew.tools.trace import clock

DAY = 86_400


def _change(now: float | int | None, before: float | int | None) -> float | None:
    """Percent change, or None when there is nothing to compare with."""
    if now is None or not before:
        return None
    return round((now - before) / before * 100, 1)


def _money(x: float | int) -> str:
    return f"${x:,.2f}"


def _ratio(part: float | int, whole: float | int) -> float | None:
    return round(part / whole, 4) if whole else None


def _one(g, q: str, params: dict):
    rows = g.ro_query(q, params).result_set
    return rows[0][0] if rows and rows[0][0] is not None else 0


def _support(g, w: dict) -> dict:
    tickets = _one(g, "MATCH (t:Ticket) WHERE t.at >= $start AND t.at < $end RETURN count(t)", w)
    before = _one(g, "MATCH (t:Ticket) WHERE t.at >= $prev AND t.at < $start RETURN count(t)", w)
    orders = _one(g, "MATCH (o:Order) WHERE o.placed_at >= $start AND o.placed_at < $end RETURN count(o)", w)
    issues = g.ro_query("MATCH (t:Ticket) WHERE t.at >= $start AND t.at < $end "
                        "RETURN t.issue_type, count(t) AS n ORDER BY n DESC LIMIT 3", w).result_set
    overdue = _one(g, "MATCH (p:Promise {status: 'broken'}) RETURN count(p)", w)
    open_tickets = _one(g, "MATCH (t:Ticket) WHERE t.status <> 'solved' RETURN count(t)", w)
    return {"tickets_this_week": tickets, "tickets_last_week": before, "tickets_change_pct": _change(tickets, before),
            "complaints_per_100_orders": f"{tickets / orders * 100:.1f} complaints per 100 orders" if orders else None,
            "top_issues": [{"issue": i.replace("_", " "), "tickets": n} for i, n in issues],
            "open_tickets": open_tickets, "overdue_commitments": overdue}


def _operations(g, w: dict) -> dict:
    delivered = g.ro_query(
        "MATCH (sc:Scan {status: 'delivered'}) WHERE sc.at >= $start AND sc.at < $end MATCH (sc)-[:FOR]->(s:Shipment) "
        "OPTIONAL MATCH (late:Scan)-[:FOR]->(s) WHERE late.late_hours > 0 "
        "RETURN count(DISTINCT s), count(DISTINCT CASE WHEN late IS NULL THEN s END)", w).result_set[0]
    total, on_time = delivered
    by_hub = g.ro_query(
        "MATCH (sc:Scan) WHERE sc.at >= $start AND sc.at < $end AND sc.status IN ['in_transit', 'delayed'] "
        "MATCH (sc)-[:AT]->(h:Hub) WITH h, count(sc) AS n, sum(CASE WHEN coalesce(sc.late_hours, 0) = 0 THEN 1 ELSE 0 END) AS ok "
        "WHERE n >= 10 RETURN h.id, toFloat(ok) / n AS rate ORDER BY rate LIMIT 1", w).result_set
    late_now = _one(g, "MATCH (s:Shipment) WHERE s.status IN ['in_transit', 'delayed'] AND s.late_hours > 0 "
                       "RETURN count(s)", w)
    broken = g.ro_query(
        "MATCH (d:Decision)-[:RESTS_ON]->(a:Assumption {status: 'broken'}) "
        "OPTIONAL MATCH (e:Evidence)-[:TESTS]->(a) WITH d, a, e ORDER BY e.window_end DESC "
        "WITH d, a, collect(e)[0] AS latest RETURN d.title, a.statement, latest.value, a.metric", w).result_set
    return {"delivered_this_week": total, "on_time_rate": _ratio(on_time, total),
            "weakest_hub": {"hub": by_hub[0][0], "on_time_rate": round(by_hub[0][1], 4)} if by_hub else None,
            "parcels_late_now": late_now,
            "decisions_not_holding": [{"decision": t, "assumed": s, "measured": round(v, 4) if v is not None else None,
                                       "measure": "on-time rate" if m == "courier_on_time_rate" else "load vs capacity"}
                                      for t, s, v, m in broken]}


def _marketing(g, w: dict) -> dict:
    orders = _one(g, "MATCH (o:Order) WHERE o.placed_at >= $start AND o.placed_at < $end RETURN count(o)", w)
    before = _one(g, "MATCH (o:Order) WHERE o.placed_at >= $prev AND o.placed_at < $start RETURN count(o)", w)
    coupon = _one(g, "MATCH (o:Order)-[:USED]->(:Coupon) WHERE o.placed_at >= $start AND o.placed_at < $end "
                     "RETURN count(DISTINCT o)", w)
    campaigns = g.ro_query(
        "MATCH (c:Campaign) WHERE c.status IN ['running', 'scheduled'] OR c.ends >= $start "
        "OPTIONAL MATCH (c)<-[:OF]-(:Coupon)<-[:USED]-(o:Order) WHERE o.placed_at >= $start AND o.placed_at < $end "
        "RETURN c.id, c.name, c.status, c.starts, c.ends, count(DISTINCT o) ORDER BY c.starts", w).result_set
    return {"orders_this_week": orders, "orders_last_week": before, "orders_change_pct": _change(orders, before),
            "coupon_share": _ratio(coupon, orders),
            "campaigns": [{"campaign": cid.upper(), "name": name, "status": status,
                           "starts_in_days": round((starts - w["end"]) / DAY) if starts > w["end"] else None,
                           "coupon_orders_this_week": n} for cid, name, status, starts, ends, n in campaigns]}


def _finance(g, w: dict) -> dict:
    revenue = _one(g, "MATCH (o:Order) WHERE o.placed_at >= $start AND o.placed_at < $end RETURN sum(o.total)", w)
    before = _one(g, "MATCH (o:Order) WHERE o.placed_at >= $prev AND o.placed_at < $start RETURN sum(o.total)", w)
    refunds = _one(g, "MATCH (r:Refund {status: 'issued'}) WHERE r.at >= $start AND r.at < $end RETURN sum(r.amount)", w)
    campaigns = g.ro_query(
        "MATCH (k:CostLine {kind: 'campaign_spend'})-[:FOR]->(c:Campaign) "
        "OPTIONAL MATCH (c)<-[:OF]-(:Coupon)<-[:USED]-(o:Order) "
        "RETURN c.id, c.name, k.amount, count(DISTINCT o), sum(o.total)", w).result_set
    couriers = g.ro_query(
        "MATCH (k:CostLine {kind: 'courier_per_parcel'})-[:FOR]->(c:Courier) "
        "OPTIONAL MATCH (c)<-[:VIA]-(s:Shipment)<-[:SHIPPED_AS]-(o:Order) WHERE o.placed_at >= $start AND o.placed_at < $end "
        "RETURN c.id, k.amount, count(DISTINCT s) ORDER BY c.id", w).result_set
    return {"revenue_this_week": _money(revenue), "revenue_last_week": _money(before),
            "revenue_change_pct": _change(revenue, before), "refunds_paid_this_week": _money(refunds),
            "campaign_spend": [{"campaign": cid.upper(), "name": name, "spend": _money(spend), "coupon_orders": n,
                                "coupon_revenue": _money(rev or 0),
                                "spend_per_coupon_order": _money(spend / n) if n else None}
                               for cid, name, spend, n, rev in campaigns],
            "delivery_cost": [{"courier": c, "per_parcel": _money(per), "parcels_this_week": n, "cost_this_week": _money(per * n)}
                              for c, per, n in couriers]}


SECTIONS = {"support": _support, "operations": _operations, "marketing": _marketing, "finance": _finance}


def company_pulse(tenant: str, user_id: str, days: int = 7) -> Answer:
    start_t = time.perf_counter()
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return unknown("company_pulse", f"user {user_id}")
    if not v.areas:
        return Answer("company_pulse", "not_permitted", reason="your role hasn't been given access to any area yet; "
                      "ask your admin", ms=round((time.perf_counter() - start_t) * 1000, 1))
    g = graph(tenant)
    end = clock(tenant)
    w = {"start": end - days * DAY, "end": end, "prev": end - 2 * days * DAY}
    sections = {area: SECTIONS[area](g, w) for area in SECTIONS if area in v.areas}  # never computed otherwise
    left_out = [a for a in SECTIONS if a not in v.areas]
    hidden = [{"kind": "area", "count": len(left_out), "reason": f"{', '.join(left_out)} figures are outside your access"}] \
        if left_out else []
    return Answer("company_pulse", "answered_path", data={"days": days, "your_areas": v.areas, **sections},
                  hidden=hidden, ms=round((time.perf_counter() - start_t) * 1000, 1))
