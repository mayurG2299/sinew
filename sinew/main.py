import json

from fastapi import FastAPI, HTTPException, Request

from sinew import config
from sinew.db import graph
from sinew.engine import pipeline, signing, snapshot

app = FastAPI(title="Sinew", version="0.1.0")


@app.get("/api/health")
def health(tenant: str = "northwind"):
    if tenant not in config.TENANTS:
        raise HTTPException(404, "unknown tenant")
    refill = snapshot.ensure_loaded(tenant)  # free instance can restart or come back older: refill if so
    g = graph(tenant)
    exists = tenant in g.client.list_graphs()  # a graph only exists after its first write
    nodes = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0] if exists else 0
    return {
        "ok": True,
        "tenant": tenant,
        "nodes": nodes,
        "refill": refill,
        "version": snapshot.graph_version(tenant) if exists else None,
        "graph_host": "local" if config.FALKORDB_HOST == "localhost" else "cloud",
    }


@app.post("/api/ingest/{tenant}")
async def ingest(tenant: str, request: Request):
    if tenant not in config.TENANTS:
        raise HTTPException(404, "unknown tenant")
    body = await request.body()
    if not signing.verify(body, request.headers.get("X-Sinew-Timestamp"),
                          request.headers.get("X-Sinew-Signature")):
        raise HTTPException(401, "bad or expired signature")
    try:
        result = pipeline.process(tenant, json.loads(body)["events"])
    except (ValueError, KeyError, TypeError) as e:  # bad JSON or an event that doesn't fit the envelope
        raise HTTPException(400, f"malformed request: {e}")
    return result.as_dict()


# ------------------------------------------------------------------ portal API
# The role switcher stands in for login in the demo: `as_user` picks who is asking, and the guard does the rest.

from pydantic import BaseModel  # noqa: E402

from sinew.agents.loop import run_agent  # noqa: E402
from sinew.engine.sdk import SinewClient  # noqa: E402
from sinew.tools import actions, guard, impact, trace  # noqa: E402


def _tenant(tenant: str) -> str:
    if tenant not in config.TENANTS:
        raise HTTPException(404, "unknown tenant")
    snapshot.ensure_loaded(tenant)
    return tenant


@app.get("/api/staff")
def staff(tenant: str = "northwind"):
    g = graph(_tenant(tenant))
    rows = g.ro_query("MATCH (u:User)-[:MEMBER_OF]->(t:Team) OPTIONAL MATCH (t)-[:COVERS]->(r:Region) "
                      "RETURN u.id, u.role, u.refund_limit, t.name, collect(r.id) ORDER BY t.name, u.role").result_set
    roster = json.loads((guard.SOURCE_RECORDS / f"{tenant}_personal.json").read_text()).get("User", {})
    return [{"id": u, "role": role, "refund_limit": limit or 0, "team": team, "regions": regions,
             "name": roster.get(u, {}).get("display_name", u)}  # from the company's own roster
            for u, role, limit, team, regions in rows]


@app.get("/api/people")
def people():
    """Everyone who can sign in to the demo, by company. A person belongs to exactly one company."""
    return [{"tenant": t, "company": name, "people": staff(t)} for t, name in
            (("northwind", "Northwind Goods"), ("larkspur", "Larkspur Home")) if t in config.TENANTS]


@app.get("/api/home")
def home_view(as_user: str, tenant: str = "northwind"):
    from sinew.home import home
    out = home(_tenant(tenant), as_user)
    if not out:
        raise HTTPException(404, "unknown user")
    return out


@app.get("/api/pulse")
def pulse_view(as_user: str, tenant: str = "northwind", days: int = 7):
    from sinew.tools.pulse import company_pulse
    return company_pulse(_tenant(tenant), as_user, days).as_dict()


@app.get("/api/briefing")
def briefing_view(as_user: str, tenant: str = "northwind"):
    from sinew.briefing import briefing
    return briefing(_tenant(tenant), as_user)


@app.get("/api/inbox")
def inbox(as_user: str, tenant: str = "northwind", limit: int = 40):
    if (refusal := guard.gate(_tenant(tenant), as_user, "inbox")):
        raise HTTPException(403, refusal["reason"])
    g = graph(_tenant(tenant))
    v = guard.Viewer.load(tenant, as_user)
    if v is None:
        raise HTTPException(404, "unknown user")
    out = [{"ticket": tid, "at": at, "issue": issue, "status": status, "summary": summary, "customer": cust,
            "region": region, "queue": queue}
           for tid, at, issue, status, summary, cust, region, queue in guard.visible_tickets(v, limit)]
    now = trace.clock(tenant)
    context = guard.inbox_context(v, sorted({t["customer"] for t in out}), now)
    for t in out:
        t.update(context[t["customer"]])
    scope = {"support_head": "all regions", "contractor": "your queue " + ", ".join(v.queues)}.get(
        v.role, "your team's regions: " + ", ".join(v.regions))
    return {"tickets": out, "now": now, "scope": scope, "can_see_customers": v.role in guard.SUPPORT_ROLES}


@app.get("/api/trace")
def customer_view(ref: str, as_user: str, tenant: str = "northwind"):
    _tenant(tenant)
    if (refusal := guard.gate(tenant, as_user, "customer_trace")):
        return {"trace": refusal, "open_loops": None, "related": None, "now": trace.clock(tenant), "freshness": []}
    t = trace.customer_trace(tenant, as_user, ref).as_dict()
    loops = trace.open_loops(tenant, as_user, ref).as_dict() if t["outcome"] == "answered_path" else None
    related = trace.related_issues(tenant, as_user, ref).as_dict() if ref.startswith("t-") and loops else None
    sources = graph(tenant).ro_query("MATCH (s:Source) RETURN s.id, s.last_event_at ORDER BY s.id").result_set
    return {"trace": t, "open_loops": loops, "related": related, "now": trace.clock(tenant),
            "freshness": [{"source": s, "last_event_at": at} for s, at in sources]}


@app.get("/api/impact")
def impact_view(as_user: str, tenant: str = "northwind", days: int = 7):
    """The Decision impact chain, computed by the graph tools alone (no AI needed). Operations area only."""
    _tenant(tenant)
    if (refusal := guard.gate(tenant, as_user, "impact")):
        raise HTTPException(403, refusal["reason"])
    clusters = impact.cluster_incidents(tenant, days).as_dict()
    root = clusters["data"]["clusters"][0]["root_hub"] if clusters["outcome"] == "answered_path" else None
    decisions = impact.trace_decisions(tenant, root).as_dict() if root else None
    # The decision whose assumption broke; a link to another decision is shown only when the data has one.
    candidates = [d for d in (decisions or {}).get("data", {}).get("decisions", [])
                  if any(a["status"] == "broken" for a in d["assumptions"])]
    candidates.sort(key=lambda d: not any(a.get("linked") for a in d["assumptions"]))
    broken = candidates[0]["decision"] if candidates else None
    return {"now": trace.clock(tenant), "clusters": clusters, "decisions": decisions,
            "impact": impact.decision_impact(tenant, broken).as_dict() if broken else None,
            "prelaunch": impact.prelaunch_check(tenant).as_dict(),
            "choke_points": impact.choke_points(tenant).as_dict()}


class AgentRequest(BaseModel):
    agent: str
    task: str
    as_user: str
    tenant: str = "northwind"


@app.post("/api/agent")
async def agent(req: AgentRequest):
    _tenant(req.tenant)
    if req.agent not in ("support", "pattern", "ask"):
        raise HTTPException(404, "unknown agent")
    if guard.Viewer.load(req.tenant, req.as_user) is None:
        raise HTTPException(404, "unknown user")
    return (await run_agent(req.tenant, req.as_user, req.agent, req.task[:500])).as_dict()


class Confirm(BaseModel):
    name: str
    args: dict
    as_user: str
    tenant: str = "northwind"


CONFIRMABLE = {
    "issue_refund": lambda t, u, a: actions.issue_refund(t, u, a["order_id"], float(a["amount"])),
    "confirm_promise": lambda t, u, a: actions.confirm_promise(t, u, a["promise_id"]),
    "file_incident": lambda t, u, a: actions.file_incident(t, u, a["title"], a["ticket_ids"], a["root_hub"]),
    "notify_owner": lambda t, u, a: actions.notify_owner(t, u, a["decision_id"], a["message"]),
}


@app.post("/api/confirm")
def confirm(req: Confirm):
    """A person confirms an action the agent prepared. It runs as that person, through the guard."""
    _tenant(req.tenant)
    if req.name not in CONFIRMABLE:
        raise HTTPException(400, "not a confirmable action")
    try:
        return CONFIRMABLE[req.name](req.tenant, req.as_user, req.args).as_dict()
    except KeyError as e:
        raise HTTPException(400, f"missing argument {e}")


@app.get("/api/privacy/export")
def privacy_export(ref: str, as_user: str, tenant: str = "northwind"):
    return actions.export_customer(_tenant(tenant), as_user, ref).as_dict()


class DeleteRequest(BaseModel):
    ref: str
    as_user: str
    tenant: str = "northwind"


@app.post("/api/privacy/delete")
def privacy_delete(req: DeleteRequest):
    return actions.delete_customer(_tenant(req.tenant), req.as_user, req.ref).as_dict()


@app.get("/api/promises")
def promises_board(as_user: str, tenant: str = "northwind"):
    if (refusal := guard.gate(_tenant(tenant), as_user, "promises")):
        raise HTTPException(403, refusal["reason"])
    g = graph(_tenant(tenant))
    v = guard.Viewer.load(tenant, as_user)
    if v is None:
        raise HTTPException(404, "unknown user")
    mine_only = v.role in ("agent", "contractor")
    rows = g.ro_query(
        "MATCH (p:Promise)-[:MADE_BY]->(u:User) WHERE p.status IN ['proposed', 'open', 'broken'] "
        "OPTIONAL MATCH (p)-[:CONCERNS]->(o:Order) OPTIONAL MATCH (p)-[:MADE_IN]->(t:Ticket) "
        "OPTIONAL MATCH (o)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) "
        "RETURN p.id, p.kind, p.status, p.due_at, u.id, o.id, t.id, c.id, p.amount ORDER BY p.due_at").result_set
    now = trace.clock(tenant)
    team = {u for u, in g.ro_query("MATCH (:User {id: $u})-[:MEMBER_OF]->(t:Team)<-[:MEMBER_OF]-(o:User) RETURN o.id",
                                   {"u": as_user}).result_set} | {as_user}
    out = [{"promise": p, "kind": k, "status": s, "due_at": due, "owner": u, "order": o, "ticket": t, "customer": c,
            "amount": amount, "hours_left": round((due - now) / 3600, 1)}
           for p, k, s, due, u, o, t, c, amount in rows
           if (u == as_user if mine_only else u in team or v.role == "support_head")]
    names = guard.customer_names(v, sorted({p["customer"] for p in out if p["customer"]}), "promises")
    for p in out:
        p["name"] = names.get(p["customer"])
    return {"now": now, "scope": "mine" if mine_only else "team", "promises": out}


@app.post("/api/demo/reset")
def demo_reset(tenant: str = "northwind"):
    snapshot.restore(_tenant(tenant))
    return {"restored": tenant, "version": snapshot.graph_version(tenant)}


@app.post("/api/demo/live-scan")
def demo_live_scan(tenant: str = "northwind", shipment: str | None = None, status: str = "delayed",
                   late_hours: int = 48):
    """Send one new courier scan through the SDK, as the courier's webhook would, to show freshness.
    Uses a real parcel of this company that is still in transit (the most recent one), never a made-up id."""
    _tenant(tenant)
    g = graph(tenant)
    rows = g.ro_query(
        "MATCH (s:Shipment) WHERE s.status IN ['in_transit', 'delayed'] AND ($s IS NULL OR s.id = $s) "
        "RETURN s.id, s.last_hub ORDER BY s.last_scan_at DESC LIMIT 1", {"s": shipment}).result_set
    if not rows:
        raise HTTPException(404, "no parcel in transit with that id")
    shipment, hub = rows[0]
    now = trace.clock(tenant) + 60
    graph(tenant).query("MATCH (m:Meta {id: 'clock'}) SET m.now = $n", {"n": now})
    event = {"event_id": f"live-{now}", "type": "scan.recorded", "source": "courier", "occurred_at": now,
             "payload": {"scan_id": f"{shipment}-live-{now}", "shipment_id": shipment, "hub_id": hub,
                         "status": status, "late_hours": late_hours}}
    return SinewClient(None, tenant).send([event])
