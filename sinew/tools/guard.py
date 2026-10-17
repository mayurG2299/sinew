"""The guard: who may see what, decided by graph paths and a fixed role policy. Never by an LLM.

- Who is asking: a Viewer, loaded from the graph (role, teams, regions, queues, refund limit).
- May they see this customer? A path must exist:
    support staff  (u)-[:MEMBER_OF]->(:Team)-[:COVERS]->(:Region)<-[:IN]-(c:Customer)
    contractor     (u)-[:MEMBER_OF]->(:Team)-[:WORKS]->(:Queue)<-[:IN]-(:Ticket)-[:FROM]->(:Profile)-[:OF]->(c)
    support head   any customer
  Other roles (logistics, marketing, analyst, CEO) have no purpose for one person's history.
- Which personal fields may they fetch live from the store? Per role, below.
- Every customer-level read leaves an Access record (ids only).
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sinew.db import graph

SUPPORT_ROLES = {"agent", "team_lead", "support_head", "contractor"}
PERSONAL_FIELDS = {  # what each role may fetch live from the store's own records
    "agent": {"name", "email", "phone"},
    "team_lead": {"name", "email", "phone", "address"},
    "support_head": {"name", "email", "phone", "address"},
    "contractor": {"name"},
}
HIDDEN_FOR = {  # timeline item kinds a role doesn't see, and why
    "contractor": {"payment": "payment details are for staff only, not contractors"},
}
SOURCE_RECORDS = Path(__file__).resolve().parents[2] / "seed" / "source"


@dataclass
class Viewer:
    user_id: str
    tenant: str
    role: str = ""
    refund_limit: float = 0
    regions: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, tenant: str, user_id: str) -> "Viewer | None":
        rows = graph(tenant).ro_query(
            "MATCH (u:User {id: $u}) "
            "OPTIONAL MATCH (u)-[:MEMBER_OF]->(t:Team) "
            "OPTIONAL MATCH (t)-[:COVERS]->(r:Region) "
            "OPTIONAL MATCH (t)-[:WORKS]->(q:Queue) "
            "RETURN u.role, u.refund_limit, collect(DISTINCT t.id), collect(DISTINCT r.id), collect(DISTINCT q.id)",
            {"u": user_id},
        ).result_set
        if not rows or rows[0][0] is None:
            return None
        role, limit, teams, regions, queues = rows[0]
        return cls(user_id, tenant, role, limit or 0, regions, queues, teams)


def customer_access(v: Viewer, customer_id: str) -> tuple[bool, str, list[str]]:
    """(allowed, reason, the path that grants it)."""
    g = graph(v.tenant)
    if v.role not in SUPPORT_ROLES:
        return False, f"role {v.role} has no support purpose for one customer's history; use the aggregate views", []
    if v.role == "support_head":
        return True, "support head: all regions", [v.user_id, customer_id]
    if v.role == "contractor":
        rows = g.ro_query(
            "MATCH (u:User {id: $u})-[:MEMBER_OF]->(t:Team)-[:WORKS]->(q:Queue)<-[:IN]-(tk:Ticket)"
            "-[:FROM]->(:Profile)-[:OF]->(c:Customer {id: $c}) RETURN t.id, q.id, tk.id LIMIT 1",
            {"u": v.user_id, "c": customer_id},
        ).result_set
        if rows:
            t, q, tk = rows[0]
            return True, f"ticket {tk} is in your queue {q}", [v.user_id, t, q, tk, customer_id]
        return False, "contractors see only customers with a ticket in their own queue", []
    # Both ends are found by index first, then the path between them is only checked (Expand Into),
    # instead of walking out to every customer in the region.
    rows = g.ro_query(
        "MATCH (u:User {id: $u}), (c:Customer {id: $c}) WITH u, c "
        "MATCH (u)-[:MEMBER_OF]->(t:Team)-[:COVERS]->(r:Region)<-[:IN]-(c) RETURN t.id, r.id LIMIT 1",
        {"u": v.user_id, "c": customer_id},
    ).result_set
    if rows:
        t, r = rows[0]
        return True, f"your team {t} covers region {r}", [v.user_id, t, r, customer_id]
    return False, "your team doesn't cover this customer's region", []


def record_access(v: Viewer, tool: str, customer_id: str | None, purpose: str = "support"):
    graph(v.tenant).query(
        "MATCH (u:User {id: $u}) CREATE (a:Access {id: $id, at: $at, tool: $tool, purpose: $purpose})-[:BY]->(u) "
        "WITH a OPTIONAL MATCH (c:Customer {id: $c}) FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | "
        "  CREATE (a)-[:OF]->(c))",
        {"u": v.user_id, "id": f"acc-{uuid.uuid4().hex[:12]}", "at": int(time.time()), "tool": tool,
         "purpose": purpose, "c": customer_id},
    )


def fetch_personal(v: Viewer, customer_id: str) -> tuple[dict, list[dict]]:
    """Fetch allowed personal fields live from the store's records (the graph has only pointers)."""
    allowed = PERSONAL_FIELDS.get(v.role, set())
    refs = graph(v.tenant).ro_query(
        "MATCH (:Customer {id: $c})<-[:OF]-(p:Profile)-[:STORED_AT]->(r:PersonalRef) RETURN r.record, r.fields",
        {"c": customer_id},
    ).result_set
    store = json.loads((SOURCE_RECORDS / f"{v.tenant}_personal.json").read_text()).get("Profile", {})
    shown, hidden = {}, []
    for record, fields in refs:
        for f in fields:
            if f in allowed:
                shown.setdefault(f, store.get(record, {}).get(f))
            else:
                hidden.append({"field": f, "reason": f"{v.role} may not see {f}"})
    for p_id in (r for r, _ in refs):
        for f in ("email", "phone"):  # matching identifiers also live only in the store
            if f in allowed and f not in shown and store.get(p_id, {}).get(f):
                shown[f] = store[p_id][f]
    return shown, hidden


def visible_tickets(v: Viewer, limit: int) -> list[list]:
    """The newest tickets this person may see, in one query that follows the same paths as customer_access."""
    g = graph(v.tenant)
    ret = ("RETURN t.id, t.at, t.issue_type, t.status, t.summary_clean, c.id, c.region, q.id "
           "ORDER BY t.at DESC LIMIT $n")
    if v.role == "support_head":
        q = ("MATCH (t:Ticket)-[:FROM]->(:Profile)-[:OF]->(c:Customer) OPTIONAL MATCH (t)-[:IN]->(q:Queue) " + ret)
    elif v.role == "contractor":
        q = ("MATCH (:User {id: $u})-[:MEMBER_OF]->(:Team)-[:WORKS]->(q:Queue)<-[:IN]-(t:Ticket) "
             "MATCH (t)-[:FROM]->(:Profile)-[:OF]->(c:Customer) " + ret)
    elif v.role in SUPPORT_ROLES:
        q = ("MATCH (:User {id: $u})-[:MEMBER_OF]->(:Team)-[:COVERS]->(:Region)<-[:IN]-(c:Customer) "
             "MATCH (c)<-[:OF]-(:Profile)<-[:FROM]-(t:Ticket) OPTIONAL MATCH (t)-[:IN]->(q:Queue) " + ret)
    else:
        return []
    return g.ro_query(q, {"u": v.user_id, "n": limit}).result_set


def inbox_context(v: Viewer, customer_ids: list[str], now: int) -> dict[str, dict]:
    """Per customer in the inbox: the display name (fetched live, only if the role may see names) and what is
    urgent for them (broken promises, promises due within a day, parcels running late). Two queries for the list.
    Each customer shown by name leaves an Access record, like opening the trace does."""
    g = graph(v.tenant)
    out = {c: {"name": None, "broken_promises": 0, "due_soon": None, "late_parcels": 0} for c in customer_ids}
    for c, broken, due, late in g.ro_query(
        "UNWIND $cs AS cid MATCH (c:Customer {id: cid})<-[:OF]-(:Profile)-[:PLACED]->(o:Order) "
        "OPTIONAL MATCH (o)<-[:CONCERNS]-(pb:Promise {status: 'broken'}) "
        "OPTIONAL MATCH (o)<-[:CONCERNS]-(po:Promise {status: 'open'}) "
        "OPTIONAL MATCH (o)-[:SHIPPED_AS]->(s:Shipment) WHERE s.status IN ['in_transit', 'delayed'] AND s.late_hours > 0 "
        "RETURN cid, count(DISTINCT pb), min(po.due_at), count(DISTINCT s)", {"cs": customer_ids}).result_set:
        out[c].update(broken_promises=broken, late_parcels=late,
                      due_soon=due if due is not None and due - now <= 86_400 else None)
    for c, n in customer_names(v, customer_ids, "inbox").items():
        out[c]["name"] = n
    return out


def customer_names(v: Viewer, customer_ids: list[str], tool: str) -> dict[str, str]:
    """Display names for a list of customers, fetched live from the store, only if this role may see names.
    Each customer shown by name leaves an Access record, like opening their trace does."""
    if "name" not in PERSONAL_FIELDS.get(v.role, set()) or not customer_ids:
        return {}
    g = graph(v.tenant)
    store = json.loads((SOURCE_RECORDS / f"{v.tenant}_personal.json").read_text()).get("Profile", {})
    names = {}
    for c, records in g.ro_query(
        "UNWIND $cs AS cid MATCH (:Customer {id: cid})<-[:OF]-(:Profile)-[:STORED_AT]->(r:PersonalRef) "
        "RETURN cid, collect(r.record)", {"cs": customer_ids}).result_set:
        name = next((store[r]["name"] for r in records if store.get(r, {}).get("name")), None)
        if name:
            names[c] = name
    g.query(
        "MATCH (u:User {id: $u}) UNWIND $cs AS cid MATCH (c:Customer {id: cid}) "
        "CREATE (a:Access {id: $id + '-' + cid, at: $at, tool: $tool, purpose: 'support'})-[:BY]->(u), (a)-[:OF]->(c)",
        {"u": v.user_id, "cs": list(names), "id": f"acc-{uuid.uuid4().hex[:12]}", "at": int(time.time()), "tool": tool})
    return names
