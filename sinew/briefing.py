"""Noticed for you: the few things Sinew found for one person, worked out from the graph (no AI).

Each notice is one line a person can act on, plus what opens when they click it: the question it asks Sinew
(answered by the agent, through the same permission checks) and the view that holds the full picture.
At most three notices, the most urgent first, and none that repeats another.
"""

from sinew.agents.check import _place as place
from sinew.db import graph
from sinew.tools import guard, impact, trace

WHY = "Why are complaints up this week, and what should we do?"
OPS_ROLES = {"logistics_manager", "marketing_manager", "ceo", "analyst", "support_head"}


def _urgency(t: dict) -> int:
    if t["status"] == "solved":
        return -1
    return t["broken_promises"] * 3 + (2 if t["due_soon"] else 0) + (2 if t["late_parcels"] else 0)


def _customer_notice(v: guard.Viewer, now: int) -> dict | None:
    rows = guard.visible_tickets(v, 40)
    if not rows:
        return None
    tickets = [{"ticket": r[0], "at": r[1], "issue": r[2], "status": r[3], "summary": r[4], "customer": r[5]} for r in rows]
    ctx = guard.inbox_context(v, sorted({t["customer"] for t in tickets}), now)
    for t in tickets:
        t.update(ctx[t["customer"]])
    tickets.sort(key=lambda t: (-_urgency(t), -t["at"]))
    top = tickets[0]
    if _urgency(top) <= 0:
        return None
    who = top["name"] or "A customer"
    title = (f"{who}'s promised refund is overdue" if top["broken_promises"]
             else f"{who}'s parcel is running late" if top["late_parcels"]
             else f"{who} has a promise due soon")
    return {"id": "customer", "tone": "urgent", "title": title,
            "detail": top["summary"],
            "ask": f"Help me with {who}'s ticket", "agent": "support",
            "task": f"Ticket {top['ticket']}: help me handle this customer.",
            "view": {"kind": "customer", "ticket": top["ticket"]}}


def _wave_notice(v: guard.Viewer, cluster: dict | None) -> dict | None:
    if not cluster:
        return None
    mine = {r[0] for r in guard.visible_tickets(v, 2000)} & set(cluster["ticket_ids"])
    if not mine:
        return None
    issue = cluster["issue"].replace("_", " ")
    return {"id": "wave", "tone": "warn",
            "title": f"{cluster['tickets']} {issue} complaints went through {place(cluster['root_hub'])} this week",
            "detail": ("All of them are from your customers." if len(mine) == cluster["tickets"]
                       else f"{len(mine)} of them are from your customers.") + " Sinew traced them back to a company decision.",
            "ask": WHY, "agent": "pattern", "task": WHY, "view": {"kind": "impact"}}


def _decision_notice(tenant: str, cluster: dict | None) -> dict | None:
    if not cluster:
        return None
    decisions = impact.trace_decisions(tenant, cluster["root_hub"]).data.get("decisions", [])
    broken = [(d, a) for d in decisions for a in d["assumptions"] if a["status"] == "broken"]
    if not broken:
        return None
    broken.sort(key=lambda x: not x[1].get("linked"))
    d, a = broken[0]
    value = f"{round(a['value'] * 100)}%" if a["metric"] == "courier_on_time_rate" else f"{a['value']:.2f}× capacity"
    return {"id": "decision", "tone": "urgent", "title": f"“{d['title']}” isn't holding up",
            "detail": f"It assumed: {a['statement']}. This week: {value}. "
                      f"{cluster['tickets']} {cluster['issue'].replace('_', ' ')} complaints went through "
                      f"{place(cluster['root_hub'])}.",
            "ask": WHY, "agent": "pattern", "task": WHY, "view": {"kind": "impact"}}


def _prelaunch_notice(tenant: str) -> dict | None:
    warnings = impact.prelaunch_check(tenant).data.get("warnings", [])
    if not warnings:
        return None
    w = warnings[0]
    route = f" Sinew found another route through {place(w['reroute']['hub'])}." if w.get("reroute") else ""
    return {"id": "prelaunch", "tone": "warn",
            "title": f"{w['name']} starts in {w['starts_in_days']:g} days through {place(w['hub'])}",
            "detail": f"That hub is already struggling.{route}",
            "ask": f"Is the {w['name']} safe to launch?", "agent": None, "task": None, "view": {"kind": "prelaunch"}}


def _promise_notice(v: guard.Viewer, now: int) -> dict | None:
    team = {u for u, in graph(v.tenant).ro_query(
        "MATCH (:User {id: $u})-[:MEMBER_OF]->(:Team)<-[:MEMBER_OF]-(o:User) RETURN o.id", {"u": v.user_id}).result_set}
    owners = [v.user_id] if v.role in ("agent", "contractor") else sorted(team | {v.user_id})
    where = "" if v.role == "support_head" else "WHERE u.id IN $owners "
    rows = graph(v.tenant).ro_query(
        f"MATCH (p:Promise)-[:MADE_BY]->(u:User) {where}"
        "RETURN sum(CASE WHEN p.status = 'broken' THEN 1 ELSE 0 END), "
        "sum(CASE WHEN p.status = 'open' AND p.due_at >= $now AND p.due_at < $now + 86400 THEN 1 ELSE 0 END)",
        {"owners": owners, "now": now}).result_set
    broken, soon = (int(x or 0) for x in rows[0]) if rows else (0, 0)
    if not broken and not soon:
        return None
    parts = [f"{broken} broken" if broken else "", f"{soon} due in the next 24 hours" if soon else ""]
    whose = "you made" if v.role in ("agent", "contractor") else "your team made"
    return {"id": "promises", "tone": "warn" if not broken else "urgent",
            "title": f"Promises: {' and '.join(p for p in parts if p)}",
            "detail": f"Refunds and deliveries {whose} to customers.",
            "ask": "Which promises need attention?", "agent": None, "task": None, "view": {"kind": "promises"}}


def briefing(tenant: str, user_id: str) -> dict:
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return {"notices": []}
    now = trace.clock(tenant)
    clusters = impact.cluster_incidents(tenant).data.get("clusters", [])
    cluster = clusters[0] if clusters else None
    notices = []
    if v.role in guard.SUPPORT_ROLES:
        notices += [_customer_notice(v, now), _promise_notice(v, now)]
        if v.role != "support_head":
            notices.append(_wave_notice(v, cluster))
    if v.role in OPS_ROLES:
        notices += [_decision_notice(tenant, cluster), _prelaunch_notice(tenant)]
    return {"notices": [n for n in notices if n][:3]}
