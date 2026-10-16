"""Decision impact tools (Hero 2) and the graph algorithms behind them.

cluster_incidents  label propagation on a ticket-to-ticket projection (tickets sharing >= 2 touched things
                   and the same issue type); each cluster is explained by what its tickets share, and its
                   root is the hub where the late scans concentrate.
trace_decisions    hub -> decisions that affect it -> their assumptions, evidence, and evidence-based links
decision_impact    forward: decisions building on it (BUILDS_ON*), keystone rank (PageRank), parcels in transit
                   through the hubs it affects, customers at risk ranked by order value, promises at risk
prelaunch_check    scheduled campaigns whose hubs already have broken assumptions, with a reroute
reroute            shortest path (SPpaths, weighted by transit hours) that avoids a hub
find_approver      nearest manager up REPORTS_TO whose refund limit covers the amount
choke_points       betweenness centrality on the hub network

Algorithms filter by label and relationship type only, so subsets are marked with a temporary label or edge
first, and always unmarked afterwards.
"""

import time
from collections import Counter

from sinew.db import graph
from sinew.tools.answer import Answer, unknown
from sinew.tools.trace import DAY, clock, resolve

MIN_CLUSTER = 5


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def cluster_incidents(tenant: str, days: int = 7) -> Answer:
    start = time.perf_counter()
    g = graph(tenant)
    now = clock(tenant)
    g.query("MATCH (t:Ticket) WHERE t.at >= $s SET t:Recent", {"s": now - days * DAY})
    try:
        g.query(
            "MATCH (a:Recent)-[:TOUCHES]->(x)<-[:TOUCHES]-(b:Recent) "
            "WHERE id(a) < id(b) AND a.issue_type = b.issue_type "
            "WITH a, b, count(DISTINCT x) AS shared WHERE shared >= 2 "
            "CREATE (a)-[:CO_TOUCH {shared: shared}]->(b)")
        rows = g.ro_query(
            "CALL algo.labelPropagation({nodeLabels: ['Recent'], relationshipTypes: ['CO_TOUCH'], "
            "maxIterations: 20}) YIELD node, communityId "
            "RETURN communityId, collect(node.id)").result_set
    finally:
        g.query("MATCH (:Recent)-[r:CO_TOUCH]->() DELETE r")
        g.query("MATCH (t:Recent) REMOVE t:Recent")
    clusters = []
    for _, tickets in rows:
        if len(tickets) < MIN_CLUSTER:
            continue
        shared = g.ro_query(
            "UNWIND $ts AS tid MATCH (t:Ticket {id: tid})-[:TOUCHES]->(x) "
            "RETURN labels(x)[0], x.id, count(t) ORDER BY count(t) DESC", {"ts": tickets}).result_set
        issue = Counter(r[0] for r in g.ro_query(
            "UNWIND $ts AS tid MATCH (t:Ticket {id: tid}) RETURN t.issue_type", {"ts": tickets}).result_set)
        late_by_hub = g.ro_query(
            "UNWIND $ts AS tid MATCH (:Ticket {id: tid})-[:ABOUT]->(:Order)-[:SHIPPED_AS]->(s:Shipment)"
            "<-[:FOR]-(sc:Scan)-[:AT]->(h:Hub) WHERE sc.late_hours > 0 "
            "RETURN h.id, count(DISTINCT s) ORDER BY count(DISTINCT s) DESC LIMIT 1", {"ts": tickets}).result_set
        root = late_by_hub[0][0] if late_by_hub else None
        clusters.append({
            "tickets": len(tickets), "ticket_ids": sorted(tickets), "issue": issue.most_common(1)[0][0],
            "shared": [{"kind": k, "id": i, "share": round(n / len(tickets), 2)} for k, i, n in shared[:6]],
            "root_hub": root, "late_parcels_at_root": late_by_hub[0][1] if late_by_hub else 0,
        })
    clusters.sort(key=lambda c: -c["tickets"])
    if not clusters:
        return Answer("cluster_incidents", "not_in_graph",
                      reason=f"no group of {MIN_CLUSTER}+ similar tickets in the last {days} days", ms=_ms(start))
    return Answer("cluster_incidents", "answered_path", data={"days": days, "clusters": clusters},
                  paths=[[f"{c['tickets']} tickets", c["root_hub"]] for c in clusters if c["root_hub"]], ms=_ms(start))


def trace_decisions(tenant: str, hub_id: str) -> Answer:
    start = time.perf_counter()
    if not resolve(tenant, "Hub", hub_id):
        return unknown("trace_decisions", f"hub {hub_id}")
    rows = graph(tenant).ro_query(
        "MATCH (d:Decision)-[:AFFECTS]->(h:Hub {id: $h}) "
        "OPTIONAL MATCH (d)-[:OWNED_BY]->(u:User) "
        "OPTIONAL MATCH (d)-[:RESTS_ON]->(a:Assumption) "
        "OPTIONAL MATCH (e:Evidence)-[:TESTS]->(a) "
        "WITH d, u, a, e ORDER BY e.window_end DESC "
        "WITH d, u, a, collect(e)[0] AS latest "
        "OPTIONAL MATCH (other:Decision)-[b:BREAKS]->(a) "
        "RETURN d.id, d.title, d.made_at, d.chose_kind, u.id, "
        "collect({assumption: a.id, statement: a.statement, metric: a.metric, op: a.op, threshold: a.threshold, "
        "status: a.status, value: latest.value, window_end: latest.window_end, linked: other.id, basis: b.basis}) "
        "ORDER BY d.made_at",
        {"h": hub_id}).result_set
    if not rows:
        return Answer("trace_decisions", "not_in_graph", reason=f"no recorded decision affects {hub_id}; "
                      "the cause stops at the hub", ms=_ms(start))
    decisions, paths = [], []
    for did, title, made_at, kind, owner, assumptions in rows:
        decisions.append({"decision": did, "title": title, "made_at": made_at, "chose": kind, "owner": owner,
                          "assumptions": [a for a in assumptions if a["assumption"]]})
        for a in assumptions:
            if a["assumption"]:
                paths.append([hub_id, did, a["assumption"]] + ([f"linked: {a['linked']}"] if a["linked"] else []))
    return Answer("trace_decisions", "answered_path", data={"hub": hub_id, "decisions": decisions}, paths=paths,
                  ms=_ms(start))


def decision_impact(tenant: str, decision_id: str) -> Answer:
    start = time.perf_counter()
    if not resolve(tenant, "Decision", decision_id):
        return unknown("decision_impact", f"decision {decision_id}")
    g = graph(tenant)
    now = clock(tenant)
    dependents = g.ro_query(
        "MATCH p = (d2:Decision)-[:BUILDS_ON*1..3]->(:Decision {id: $d}) "
        "RETURN d2.id, d2.title, length(p)", {"d": decision_id}).result_set
    keystone = g.ro_query(
        "CALL algo.pageRank('Decision', 'BUILDS_ON') YIELD node, score RETURN node.id, score ORDER BY score DESC"
    ).result_set
    rank = {d: i + 1 for i, (d, _) in enumerate(keystone)}
    hubs = [r[0] for r in g.ro_query("MATCH (:Decision {id: $d})-[:AFFECTS]->(h:Hub) RETURN h.id",
                                     {"d": decision_id}).result_set]
    at_risk = g.ro_query(
        "MATCH (s:Shipment) WHERE s.last_hub IN $hubs AND s.status IN ['in_transit', 'delayed'] "
        "MATCH (s)<-[:SHIPPED_AS]-(o:Order)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) "
        "OPTIONAL MATCH (c)<-[:OF]-(:Profile)<-[:FROM]-(t:Ticket) WHERE t.status <> 'solved' "
        "RETURN c.id, c.tier, sum(DISTINCT o.total) AS value, collect(DISTINCT o.id), count(DISTINCT t), "
        "max(s.late_hours) ORDER BY value DESC", {"hubs": hubs}).result_set
    promises = g.ro_query(
        "MATCH (s:Shipment) WHERE s.last_hub IN $hubs AND s.status IN ['in_transit', 'delayed'] "
        "MATCH (s)<-[:SHIPPED_AS]-(o:Order)<-[:CONCERNS]-(p:Promise) WHERE p.status IN ['open', 'proposed'] "
        "OPTIONAL MATCH (p)-[:MADE_IN]->(t:Ticket) "
        "RETURN p.id, p.kind, p.due_at, o.id, t.id ORDER BY p.due_at", {"hubs": hubs}).result_set
    data = {
        "decision": decision_id, "keystone_rank": rank.get(decision_id), "decisions_ranked": len(rank),
        "dependent_decisions": [{"decision": d, "title": t, "hops": n} for d, t, n in dependents],
        "hubs": hubs,
        "parcels_in_transit": sum(len(r[3]) for r in at_risk),
        "customers_at_risk": [{"customer": c, "tier": tier, "order_value": round(v, 2), "orders": o,
                               "open_tickets": t, "late_hours": late} for c, tier, v, o, t, late in at_risk],
        "promises_at_risk": [{"promise": p, "kind": k, "due_at": due, "order": o, "ticket": t,
                              "hours_left": round((due - now) / 3600, 1)} for p, k, due, o, t in promises],
    }
    paths = [[decision_id, h] for h in hubs] + [[d, "BUILDS_ON", decision_id] for d, _, _ in dependents]
    return Answer("decision_impact", "answered_path", data=data, paths=paths, ms=_ms(start))


def reroute(tenant: str, from_hub: str, avoid_hub: str) -> Answer:
    """Best other last-mile hub in the avoided hub's region, by transit hours, with the avoided hub blocked."""
    start = time.perf_counter()
    for h in (from_hub, avoid_hub):
        if not resolve(tenant, "Hub", h):
            return unknown("reroute", f"hub {h}")
    g = graph(tenant)
    g.query("MATCH (:Hub {id: $h})-[r:ROUTES_TO]-() SET r.blocked = 1", {"h": avoid_hub})
    try:
        current = g.ro_query(
            "MATCH (a:Hub {id: $a}), (b:Hub {id: $b}) "
            "CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROUTES_TO'], weightProp: 'transit_h', "
            "pathCount: 1}) YIELD path, pathWeight RETURN [n IN nodes(path) | n.id], pathWeight",
            {"a": from_hub, "b": avoid_hub}).result_set
        options = g.ro_query(
            "MATCH (a:Hub {id: $a}), (x:Hub {id: $x})-[:IN]->(r:Region)<-[:IN]-(b:Hub) WHERE b <> x AND b <> a "
            "CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROUTES_TO'], weightProp: 'transit_h', "
            "costProp: 'blocked', maxCost: 0, pathCount: 1}) YIELD path, pathWeight "
            "RETURN b.id, [n IN nodes(path) | n.id], pathWeight, b.capacity ORDER BY pathWeight",
            {"a": from_hub, "x": avoid_hub}).result_set
    finally:
        g.query("MATCH (:Hub {id: $h})-[r:ROUTES_TO]-() SET r.blocked = 0", {"h": avoid_hub})
    if not options:
        return Answer("reroute", "not_in_graph", reason=f"no route from {from_hub} avoids {avoid_hub}", ms=_ms(start))
    best = options[0]
    return Answer("reroute", "answered_path", data={
        "avoid": avoid_hub, "current": {"path": current[0][0], "hours": current[0][1]} if current else None,
        "best": {"hub": best[0], "path": best[1], "hours": best[2], "capacity": best[3]},
        "options": [{"hub": h, "path": p, "hours": w} for h, p, w, _ in options]},
        paths=[best[1]], ms=_ms(start))


def prelaunch_check(tenant: str) -> Answer:
    start = time.perf_counter()
    g = graph(tenant)
    now = clock(tenant)
    rows = g.ro_query(
        "MATCH (k:Campaign) WHERE k.starts > $now "
        "MATCH (d:Decision)-[:CHOSE]->(k) MATCH (d)-[:AFFECTS]->(h:Hub)<-[:ABOUT]-(a:Assumption {status: 'broken'}) "
        "OPTIONAL MATCH (e:Evidence)-[:CONTRADICTS]->(a) WITH k, d, h, a, e ORDER BY e.window_end DESC "
        "WITH k, d, h, a, collect(e)[0] AS latest "
        "RETURN k.id, k.name, k.starts, d.id, h.id, collect(DISTINCT {assumption: a.id, statement: a.statement, "
        "value: latest.value, threshold: a.threshold, metric: a.metric})", {"now": now}).result_set
    if not rows:
        return Answer("prelaunch_check", "not_in_graph", reason="no scheduled campaign touches a hub with a "
                      "broken assumption", ms=_ms(start))
    warnings = []
    for kid, name, starts, did, hub, broken in rows:
        # Where parcels for this hub actually come from: the earlier hub in their own scan history.
        upstream = g.ro_query(
            "MATCH (s:Shipment {last_hub: $h})<-[:FOR]-(sc:Scan)-[:AT]->(u:Hub) WHERE u.id <> $h "
            "RETURN u.id, count(*) AS n ORDER BY n DESC LIMIT 1", {"h": hub}).result_set
        options = reroute(tenant, upstream[0][0], hub) if upstream else None
        warnings.append({"campaign": kid, "name": name, "starts_in_days": round((starts - now) / DAY, 1),
                         "decision": did, "hub": hub, "broken_assumptions": broken,
                         "reroute": options.data.get("best") if options and options.outcome == "answered_path" else None})
    return Answer("prelaunch_check", "answered_path", data={"warnings": warnings},
                  paths=[[w["campaign"], w["decision"], w["hub"]] + [b["assumption"] for b in w["broken_assumptions"]]
                         for w in warnings], ms=_ms(start))


def find_approver(tenant: str, user_id: str, amount: float) -> Answer:
    start = time.perf_counter()
    if not resolve(tenant, "User", user_id):
        return unknown("find_approver", f"user {user_id}")
    rows = graph(tenant).ro_query(
        "MATCH (a:User {id: $u}) WHERE coalesce(a.refund_limit, 0) >= $amt RETURN a.id, 0, [a.id]",
        {"u": user_id, "amt": amount}).result_set or graph(tenant).ro_query(
        "MATCH (a:User {id: $u}) MATCH (b:User) WHERE b.refund_limit >= $amt "
        "CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['REPORTS_TO'], relDirection: 'outgoing', "
        "pathCount: 1}) YIELD path "
        "RETURN b.id, length(path), [n IN nodes(path) | n.id] ORDER BY length(path) LIMIT 1",
        {"u": user_id, "amt": amount}).result_set
    if not rows:
        return Answer("find_approver", "not_in_graph", reason=f"no one above {user_id} can approve {amount}",
                      ms=_ms(start))
    approver, hops, path = rows[0]
    return Answer("find_approver", "answered_path", data={"amount": amount, "approver": approver, "hops": hops,
                  "self": hops == 0}, paths=[path], ms=_ms(start))


def choke_points(tenant: str, top: int = 3) -> Answer:
    start = time.perf_counter()
    rows = graph(tenant).ro_query(
        "CALL algo.betweenness({nodeLabels: ['Hub'], relationshipTypes: ['ROUTES_TO'], samplingSize: 100, "
        "samplingSeed: 42}) YIELD node, score RETURN node.id, score ORDER BY score DESC LIMIT $n",
        {"n": top}).result_set
    return Answer("choke_points", "answered_path", data=[{"hub": h, "score": s} for h, s in rows],
                  paths=[[h] for h, _ in rows], ms=_ms(start))
