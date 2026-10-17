"""The home screen for one person, worked out from the graph (no AI).

The frame is the same for everyone; what fills it depends on the person's job and what they may see:
  counts      open · needs your attention · at risk
  attention   who or what needs them, and for how long (details open on click)
  at_risk     what may need them soon
  insights    at most two things Sinew noticed, each opening a question for the AI
Every item carries what opens when it is clicked: a question for the AI and/or a detail view.
"""

from sinew.agents.check import _place as place
from sinew.briefing import WHY, _urgency
from sinew.db import graph
from sinew.tools import guard, impact, trace

LEADERS = {"ceo", "analyst", "support_head", "cmo"}
PULSE = "How is the company doing this week?"


def _pulse_insight() -> dict:
    return {"id": "pulse", "text": "A summary of how the company is doing this week, for your role.", "ask": PULSE,
            "agent": "ask", "task": PULSE, "view": None}


def _item(id_, label, ask, agent=None, task=None, view=None, since=None, note=None):
    return {"id": id_, "label": label, "since": since, "note": note, "ask": ask, "agent": agent, "task": task, "view": view}


def _support(v: guard.Viewer, now: int, cluster: dict | None, risk_customers: set[str]) -> dict:
    rows = guard.visible_tickets(v, 2000)
    open_rows = [r for r in rows if r[3] != "solved"]
    latest = {}
    for tid, at, issue, status, summary, cust, region, queue in open_rows:  # newest open ticket per customer
        if cust not in latest or at > latest[cust]["at"]:
            latest[cust] = {"ticket": tid, "at": at, "status": status, "customer": cust}
    ctx = guard.inbox_context(v, sorted(latest), now)
    people = [dict(t, **ctx[c]) for c, t in latest.items()]
    attention = sorted((p for p in people if _urgency(p) > 0), key=lambda p: (-_urgency(p), p["at"]))
    at_risk = [p for p in people if p["customer"] in risk_customers and _urgency(p) <= 0]
    item = lambda p: _item(p["ticket"], p["name"] or "A customer", f"Help me with {p['name'] or 'this customer'}'s ticket",
                           "support", f"Ticket {p['ticket']}: help me handle this customer.",
                           {"kind": "customer", "ticket": p["ticket"]}, since=p["at"])
    insights = []
    if cluster and "operations" in v.areas:  # the decision behind it is operations information
        mine = {r[0] for r in rows} & set(cluster["ticket_ids"])
        if mine:
            insights.append({"id": "wave", "text": f"{len(mine)} of your customers' complaints this week share one route: "
                             f"{place(cluster['root_hub'])}. Sinew found a company decision behind it.",
                             "ask": WHY, "agent": "pattern", "task": WHY, "view": {"kind": "impact"}})
    return {"counts": {"open": len(open_rows), "attention": len(attention), "at_risk": len(at_risk)},
            "open_label": "open tickets",
            "attention": [item(p) for p in attention], "at_risk": [item(p) for p in at_risk], "insights": insights}


def _decisions(tenant: str, v: guard.Viewer, cluster: dict | None) -> dict:
    g = graph(tenant)
    mine_only = v.role not in LEADERS
    rows = g.ro_query(
        "MATCH (d:Decision)-[:OWNED_BY]->(u:User) OPTIONAL MATCH (d)-[:RESTS_ON]->(a:Assumption {status: 'broken'}) "
        "OPTIONAL MATCH (d)-[:BREAKS]->(b:Assumption {status: 'broken'})<-[:RESTS_ON]-(other:Decision) "
        "RETURN d.id, d.title, u.id, collect(DISTINCT a.id), collect(DISTINCT other.title)", {}).result_set
    attention = []
    for did, title, owner, broken, overlaps in rows:
        if mine_only and owner != v.user_id:
            continue
        if broken:
            ev = g.ro_query("MATCH (:Assumption {id: $a})<-[:TESTS]-(e:Evidence) RETURN e.value, e.metric "
                            "ORDER BY e.window_end DESC LIMIT 1", {"a": broken[0]}).result_set
            note = None
            if ev:
                value, metric = ev[0]
                note = f"{round(value * 100)}% now" if metric == "courier_on_time_rate" else f"{value:.2f}× capacity"
            attention.append(_item(did, title, WHY, "pattern", WHY, {"kind": "impact"}, note=note))
        elif overlaps:
            attention.append(_item(did, title, WHY, "pattern", WHY, {"kind": "impact"}, note="overlaps another decision"))
    warnings = impact.prelaunch_check(tenant).data.get("warnings", [])
    at_risk = [_item(w["campaign"], w["name"], f"Is the {w['name']} safe to launch?", view={"kind": "prelaunch"},
                     note=f"starts in {w['starts_in_days']:g} days") for w in warnings]
    in_scope = sum(1 for did, title, owner, *_ in rows if not mine_only or owner == v.user_id)
    insights = []
    if cluster:
        insights.append({"id": "wave", "text": f"{cluster['tickets']} complaints this week share one route: "
                         f"{place(cluster['root_hub'])}. Sinew checked which decisions rely on it.",
                         "ask": WHY, "agent": "pattern", "task": WHY, "view": {"kind": "impact"}})
    return {"counts": {"open": in_scope, "attention": len(attention), "at_risk": len(at_risk)},
            "open_label": "your decisions" if mine_only else "decisions",
            "attention": attention, "at_risk": at_risk, "insights": insights}


def home(tenant: str, user_id: str) -> dict:
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return {}
    now = trace.clock(tenant)
    clusters = impact.cluster_incidents(tenant).data.get("clusters", [])
    cluster = clusters[0] if clusters else None
    if v.role in guard.SUPPORT_ROLES and v.role != "support_head" and "support" in v.areas:
        risk = set()
        if cluster:
            decisions = impact.trace_decisions(tenant, cluster["root_hub"]).data.get("decisions", [])
            broken = next((d["decision"] for d in decisions if any(a["status"] == "broken" for a in d["assumptions"])), None)
            if broken:
                risk = {c["customer"] for c in impact.decision_impact(tenant, broken).data.get("customers_at_risk", [])}
        out = _support(v, now, cluster, risk)
    elif "operations" in v.areas:
        out = _decisions(tenant, v, cluster)
    else:  # a role with no area for a home list: just the summary of what they may see
        out = {"counts": {"open": 0, "attention": 0, "at_risk": 0}, "open_label": "open", "attention": [],
               "at_risk": [], "insights": []}
    if v.areas:
        out["insights"] = out["insights"][:1] + [_pulse_insight()]
    return {"now": now, "areas": v.areas, **out}
