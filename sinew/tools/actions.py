"""Write tools. Two kinds, and the difference matters (ENGINE.md §1 rule 4):

- Actions on the business (refunds, promises): they go to the source system, and the result comes back
  into the graph as an ordinary event through the pipeline. Here the "source" is the simulator's store,
  so the action emits the event the store would send. The graph is never edited around the pipeline.
- Sinew's own records (incidents, findings, notifications, deletions): written directly, through the guard.

Every write names the person it runs as (bound by the MCP server, never chosen by the model) and is tied to
an AgentRun for provenance. Money and anything over a limit need a person: the tool returns who can approve.
"""

import time
import uuid

from sinew.db import graph
from sinew.engine import assumptions, pipeline
from sinew.engine.minimise import redact
from sinew.tools import guard
from sinew.tools.answer import Answer, refused, unknown
from sinew.tools.impact import find_approver
from sinew.tools.trace import DAY, clock, resolve, resolve_customer

INCIDENT_ROLES = {"team_lead", "support_head", "logistics_manager"}
PRIVACY_ROLES = {"support_head"}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _provenance(tenant: str, run_id: str | None, user_id: str, label: str, node_id: str):
    if run_id:
        graph(tenant).query(
            "MERGE (r:AgentRun {id: $run}) ON CREATE SET r.at = $at, r.as_user = $u "
            "WITH r MATCH (n:" + label + " {id: $n}) MERGE (r)-[:WROTE]->(n)",
            {"run": run_id, "at": int(time.time()), "u": user_id, "n": node_id})


def _viewer_for_customer_of_order(tenant: str, user_id: str, order_id: str):
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return None, unknown("action", f"user {user_id}")
    if not resolve(tenant, "Order", order_id):
        return None, unknown("action", f"order {order_id}")
    customer = resolve_customer(tenant, order_id)
    allowed, reason, _ = guard.customer_access(v, customer, write=True)
    if not allowed:
        return None, refused("action", reason)
    return v, None


def issue_refund(tenant: str, user_id: str, order_id: str, amount: float, run_id: str | None = None) -> Answer:
    v, stop = _viewer_for_customer_of_order(tenant, user_id, order_id)
    if stop:
        stop.tool = "issue_refund"
        return stop
    total = graph(tenant).ro_query("MATCH (o:Order {id: $o}) RETURN o.total", {"o": order_id}).result_set[0][0]
    if amount <= 0 or amount > total:
        return Answer("issue_refund", "not_permitted", reason=f"amount must be between 0 and the order total {total}")
    if amount > v.refund_limit:
        approver = find_approver(tenant, user_id, amount)
        return Answer("issue_refund", "needs_approval", data={"amount": amount, "limit": v.refund_limit,
                      "approver": approver.data.get("approver")}, paths=approver.paths,
                      reason=f"{amount} is above your limit of {v.refund_limit}")
    refund_id = _id("rf")
    now = clock(tenant)
    # The payment system issues it and sends the event back; here the simulator stands in for it.
    pipeline.process(tenant, [{"event_id": f"evt-{refund_id}", "type": "refund.issued", "source": "payments",
                               "occurred_at": now, "payload": {"refund_id": refund_id, "order_id": order_id,
                                                               "amount": amount, "status": "issued",
                                                               "approved_by": user_id}}])
    _provenance(tenant, run_id, user_id, "Refund", refund_id)
    kept = graph(tenant).ro_query("MATCH (p:Promise)-[:KEPT_BY]->(:Refund {id: $r}) RETURN p.id, p.status",
                                  {"r": refund_id}).result_set
    return Answer("issue_refund", "answered_path", data={"refund": refund_id, "order": order_id, "amount": amount,
                  "promises_settled": [{"promise": p, "status": s} for p, s in kept]},
                  paths=[[user_id, refund_id, order_id]])


def record_promise(tenant: str, user_id: str, ticket_id: str, order_id: str, kind: str, due_in_hours: float,
                   run_id: str | None = None) -> Answer:
    """The AI proposes a promise it found in the agent's reply; a person (or the matching action) confirms it."""
    v, stop = _viewer_for_customer_of_order(tenant, user_id, order_id)
    if stop:
        stop.tool = "record_promise"
        return stop
    if not resolve(tenant, "Ticket", ticket_id):
        return unknown("record_promise", f"ticket {ticket_id}")
    promise_id = _id("pr")
    now = clock(tenant)
    r = pipeline.process(tenant, [{"event_id": f"evt-{promise_id}", "type": "promise.proposed", "source": "sinew-ai",
                                   "occurred_at": now, "payload": {
                                       "promise_id": promise_id, "ticket_id": ticket_id, "order_id": order_id,
                                       "kind": kind, "due_at": now + int(due_in_hours * 3600), "made_by": user_id}}])
    if r.quarantined:
        return Answer("record_promise", "not_permitted", reason=r.quarantined[0]["reason"])
    _provenance(tenant, run_id, user_id, "Promise", promise_id)
    return Answer("record_promise", "answered_path", data={"promise": promise_id, "status": "proposed",
                  "next": "the agent confirms it, or the matching action confirms it"},
                  paths=[[ticket_id, promise_id, order_id]])


def confirm_promise(tenant: str, user_id: str, promise_id: str) -> Answer:
    if not resolve(tenant, "Promise", promise_id):
        return unknown("confirm_promise", f"promise {promise_id}")
    stop = _may_confirm(tenant, user_id, promise_id)
    if stop:
        return stop
    pipeline.process(tenant, [{"event_id": f"evt-confirm-{promise_id}", "type": "promise.confirmed",
                               "source": "sinew-ai", "occurred_at": clock(tenant),
                               "payload": {"promise_id": promise_id, "confirmed_by": user_id}}])
    status = graph(tenant).ro_query("MATCH (p:Promise {id: $p}) RETURN p.status", {"p": promise_id}).result_set[0][0]
    return Answer("confirm_promise", "answered_path", data={"promise": promise_id, "status": status})


def _may_confirm(tenant: str, user_id: str, promise_id: str) -> Answer | None:
    """Only the person who made the commitment, or a lead / head of support, may confirm it."""
    v = guard.Viewer.load(tenant, user_id)
    maker = graph(tenant).ro_query("MATCH (:Promise {id: $p})-[:MADE_BY]->(u:User) RETURN u.id", {"p": promise_id}).result_set
    if v is None or (maker and maker[0][0] != user_id and v.role not in ("team_lead", "support_head")):
        return refused("confirm_promise", "only the person who made it, or their team lead, can confirm it")
    return None


def precheck(tenant: str, user_id: str, name: str, args: dict) -> dict | None:
    """Before an action is offered to a person as a button: would it be allowed for them? None if yes, else
    the refusal. (The action checks again when they click; this only stops buttons that can never work.)"""
    tool_gate = guard.gate(tenant, user_id, name)
    if tool_gate:
        return tool_gate
    v = guard.Viewer.load(tenant, user_id)
    if name == "file_incident" and v.role not in INCIDENT_ROLES:
        return refused(name, "opening incidents is for team leads, the head of support or logistics managers").as_dict()
    if name == "issue_refund":
        _, stop = _viewer_for_customer_of_order(tenant, user_id, args.get("order_id", ""))
        return stop.as_dict() if stop else None
    if name == "confirm_promise":
        stop = _may_confirm(tenant, user_id, args.get("promise_id", ""))
        return stop.as_dict() if stop else None
    return None


def file_incident(tenant: str, user_id: str, title: str, ticket_ids: list[str], root_hub: str,
                  run_id: str | None = None) -> Answer:
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return unknown("file_incident", f"user {user_id}")
    if v.role not in INCIDENT_ROLES:
        return refused("file_incident", "only team leads, the head of support or logistics managers can open incidents")
    if not resolve(tenant, "Hub", root_hub):
        return unknown("file_incident", f"hub {root_hub}")
    incident_id = _id("inc")
    g = graph(tenant)
    g.query(
        "MATCH (h:Hub {id: $h}), (u:User {id: $u}) "
        "CREATE (i:Incident {id: $id, title: $title, opened_at: $at, status: 'open'})-[:ROOT]->(h), "
        "(i)-[:FILED_BY]->(u) "
        "WITH i UNWIND $tickets AS tid MATCH (t:Ticket {id: tid}) MERGE (t)-[:PART_OF]->(i)",
        {"h": root_hub, "u": user_id, "id": incident_id, "title": redact(title)[:200], "at": clock(tenant),
         "tickets": ticket_ids})
    _provenance(tenant, run_id, user_id, "Incident", incident_id)
    linked = g.ro_query("MATCH (t:Ticket)-[:PART_OF]->(:Incident {id: $i}) RETURN count(t)",
                        {"i": incident_id}).result_set[0][0]
    return Answer("file_incident", "answered_path", data={"incident": incident_id, "tickets_linked": linked,
                  "root": root_hub}, paths=[[incident_id, root_hub]])


def evaluate_assumptions(tenant: str) -> Answer:
    """Run the assumption checks now (the daily job). Marks broken ones and records evidence."""
    out = assumptions.evaluate(tenant, now=clock(tenant))
    return Answer("evaluate_assumptions", "answered_path", data=out)


def notify_owner(tenant: str, user_id: str, decision_id: str, message: str, run_id: str | None = None) -> Answer:
    rows = graph(tenant).ro_query("MATCH (:Decision {id: $d})-[:OWNED_BY]->(u:User) RETURN u.id",
                                  {"d": decision_id}).result_set
    if not rows:
        return unknown("notify_owner", f"decision {decision_id}")
    note_id = _id("note")
    graph(tenant).query(
        "MATCH (d:Decision {id: $d}), (to:User {id: $to}), (from:User {id: $from}) "
        "CREATE (n:Notification {id: $id, text: $text, at: $at, read: false})-[:TO]->(to), "
        "(n)-[:ABOUT]->(d), (n)-[:FROM]->(from)",
        {"d": decision_id, "to": rows[0][0], "from": user_id, "id": note_id, "text": redact(message)[:600],
         "at": clock(tenant)})
    _provenance(tenant, run_id, user_id, "Notification", note_id)
    return Answer("notify_owner", "answered_path", data={"notification": note_id, "to": rows[0][0]},
                  paths=[[note_id, decision_id, rows[0][0]]])


def write_finding(tenant: str, user_id: str, about: list[str], text: str, run_id: str | None = None) -> Answer:
    """Memory as nodes: what an agent concluded, tied to the things it is about, with a date."""
    finding_id = _id("fd")
    g = graph(tenant)
    g.query("CREATE (f:Finding {id: $id, text: $text, at: $at, by: $u})",
            {"id": finding_id, "text": redact(text)[:600], "at": clock(tenant), "u": user_id})
    linked = 0
    for node_id in about:
        linked += g.query("MATCH (f:Finding {id: $f}), (x {id: $x}) WHERE NOT x:Finding "
                          "MERGE (f)-[:ABOUT]->(x) RETURN count(x)", {"f": finding_id, "x": node_id}).result_set[0][0]
    _provenance(tenant, run_id, user_id, "Finding", finding_id)
    return Answer("write_finding", "answered_path", data={"finding": finding_id, "linked_to": linked})


def recall(tenant: str, about: str, limit: int = 5) -> Answer:
    rows = graph(tenant).ro_query(
        "MATCH (f:Finding)-[:ABOUT]->({id: $x}) RETURN f.id, f.text, f.at, f.by ORDER BY f.at DESC LIMIT $n",
        {"x": about, "n": limit}).result_set
    if not rows:
        return Answer("recall", "not_in_graph", reason=f"no earlier findings about {about}")
    return Answer("recall", "answered_memory", data=[{"finding": f, "text": t, "at": at, "by": by}
                                                     for f, t, at, by in rows], paths=[[r[0], about] for r in rows])


# ------------------------------------------------------------------ privacy: export and delete-me


def export_customer(tenant: str, user_id: str, ref: str) -> Answer:
    v = guard.Viewer.load(tenant, user_id)
    if v is None or v.role not in PRIVACY_ROLES:
        return refused("export_customer", "privacy requests are handled by the support head")
    customer = resolve_customer(tenant, ref)
    if customer is None:
        return unknown("export_customer", f"customer {ref!r}")
    g = graph(tenant)
    # Only records that belong to this person, each by its own directed path. (A loose "anything within two
    # hops" walk reaches other customers through shared things like a region, so it is never used here.)
    parts = {
        "Profile": "(c)<-[:OF]-(x:Profile)",
        "Identifier": "(c)<-[:OF]-(:Profile)-[:HAS]->(x:Identifier)",
        "PersonalRef": "(c)<-[:OF]-(:Profile)-[:STORED_AT]->(x:PersonalRef)",
        "Consent": "(c)<-[:OF]-(:Profile)-[x:CONSENTED]->(:Purpose)",
        "Order": "(c)<-[:OF]-(:Profile)-[:PLACED]->(x:Order)",
        "LineItem": "(c)<-[:OF]-(:Profile)-[:PLACED]->(:Order)-[:HAS]->(x:LineItem)",
        "Payment": "(c)<-[:OF]-(:Profile)-[:PLACED]->(:Order)-[:PAID_BY]->(x:Payment)",
        "Shipment": "(c)<-[:OF]-(:Profile)-[:PLACED]->(:Order)-[:SHIPPED_AS]->(x:Shipment)",
        "Scan": "(c)<-[:OF]-(:Profile)-[:PLACED]->(:Order)-[:SHIPPED_AS]->(:Shipment)<-[:FOR]-(x:Scan)",
        "Refund": "(c)<-[:OF]-(:Profile)-[:PLACED]->(:Order)<-[:FOR]-(x:Refund)",
        "Return": "(c)<-[:OF]-(:Profile)-[:PLACED]->(:Order)-[:HAS]->(:LineItem)<-[:OF]-(x:Return)",
        "Promise": "(c)<-[:OF]-(:Profile)-[:PLACED]->(:Order)<-[:CONCERNS]-(x:Promise)",
        "Ticket": "(c)<-[:OF]-(:Profile)<-[:FROM]-(x:Ticket)",
    }
    held = [(label, g.ro_query(f"MATCH (c:Customer {{id: $c}}) MATCH {path} RETURN count(DISTINCT x)",
                               {"c": customer}).result_set[0][0]) for label, path in parts.items()]
    accesses = g.ro_query("MATCH (a:Access)-[:OF]->(:Customer {id: $c}) RETURN count(a)", {"c": customer}).result_set
    guard.record_access(v, "export_customer", customer, purpose="privacy")
    return Answer("export_customer", "answered_path", data={
        "customer": customer, "graph_holds": {k: n for k, n in held if n},
        "access_records": accesses[0][0],
        "note": "names, emails, phones and addresses are not in the graph; the store holds them"})


def delete_customer(tenant: str, user_id: str, ref: str, run_id: str | None = None) -> Answer:
    """Delete-me: remove the person's identity from the graph, keep business records unlinked, prove it."""
    v = guard.Viewer.load(tenant, user_id)
    if v is None or v.role not in PRIVACY_ROLES:
        return refused("delete_customer", "privacy requests are handled by the support head")
    customer = resolve_customer(tenant, ref)
    if customer is None:
        return unknown("delete_customer", f"customer {ref!r}")
    g = graph(tenant)
    profiles = [r[0] for r in g.ro_query("MATCH (:Customer {id: $c})<-[:OF]-(p:Profile) RETURN p.id",
                                         {"c": customer}).result_set]
    tomb = _id("tomb")
    now = clock(tenant)
    # Orders, refunds and tickets stay (tax and dispute law) but are re-pointed at an anonymous tombstone.
    g.query("CREATE (:Tombstone {id: $t, deleted_at: $at, profiles: $n})", {"t": tomb, "at": now, "n": len(profiles)})
    g.query("MATCH (p:Profile)-[r:PLACED]->(o:Order) WHERE p.id IN $ps MATCH (t:Tombstone {id: $t}) "
            "CREATE (t)-[:PLACED]->(o) DELETE r", {"ps": profiles, "t": tomb})
    g.query("MATCH (tk:Ticket)-[r:FROM]->(p:Profile) WHERE p.id IN $ps MATCH (t:Tombstone {id: $t}) "
            "CREATE (tk)-[:FROM]->(t) DELETE r", {"ps": profiles, "t": tomb})
    g.query("MATCH (a:Access)-[r:OF]->(:Customer {id: $c}) MATCH (t:Tombstone {id: $t}) "
            "CREATE (a)-[:OF]->(t) DELETE r", {"c": customer, "t": tomb})
    g.query("MATCH (f:Finding)-[:ABOUT]->(x) WHERE x.id = $c OR x.id IN $ps DETACH DELETE f",
            {"c": customer, "ps": profiles})
    # Identity: profiles, their hashed identifiers (unless another profile still uses them), pointers, customer.
    g.query("MATCH (p:Profile)-[:HAS]->(i:Identifier) WHERE p.id IN $ps "
            "OPTIONAL MATCH (i)<-[:HAS]-(o:Profile) WHERE NOT o.id IN $ps "
            "WITH i, count(o) AS others WHERE others = 0 DETACH DELETE i", {"ps": profiles})
    g.query("MATCH (p:Profile)-[:STORED_AT]->(r:PersonalRef) WHERE p.id IN $ps DETACH DELETE r", {"ps": profiles})
    g.query("MATCH (p:Profile) WHERE p.id IN $ps DETACH DELETE p", {"ps": profiles})
    g.query("MATCH (c:Customer {id: $c}) DETACH DELETE c", {"c": customer})
    # The deletion request to the store itself, which holds the personal fields.
    g.query("CREATE (:DeletionRequest {id: $id, source: 'store', records: $ps, at: $at, status: 'sent'})",
            {"id": _id("del"), "ps": profiles, "at": now})
    _provenance(tenant, run_id, user_id, "Tombstone", tomb)
    proof = g.ro_query("MATCH (n) WHERE n.id = $c OR n.id IN $ps RETURN count(n)",
                       {"c": customer, "ps": profiles}).result_set[0][0]
    by_id = resolve_customer(tenant, customer)
    by_order = g.ro_query("MATCH (:Tombstone {id: $t})-[:PLACED]->(o:Order) OPTIONAL MATCH (o)<-[:PLACED]-(p:Profile) "
                          "RETURN count(p)", {"t": tomb}).result_set[0][0]
    return Answer("delete_customer", "answered_path", data={
        "customer": customer, "profiles_removed": len(profiles), "tombstone": tomb,
        "proof": {"nodes_left_with_their_ids": proof, "resolves_now": by_id, "orders_still_linked_to_a_person": by_order},
        "kept_unlinked": "orders, payments, refunds and tickets (legal retention), now pointing at the tombstone",
        "store": "deletion request sent to the store for names, emails, phones and addresses"})
