"""Speed pass: profile Sinew's main read queries with FalkorDB's own GRAPH.PROFILE and timings.

For each named query: the median internal execution time over repeated runs (FalkorDB's "Query internal
execution time", so no network), and the most rows any plan step produced (the work it did).
Writes docs/perf.md. Run:  SINEW_LOCAL=1 uv run python -m sinew.perf northwind
"""

import json
import re
import statistics
import sys
from pathlib import Path

from sinew.db import client, graph

RUNS = 30
AFTER = False  # set by the command line: compare the query forms before and after the speed pass
DOCS = Path(__file__).resolve().parents[1] / "docs"


def profile(tenant: str, cypher: str, params: dict) -> tuple[float, int, list[str]]:
    g = graph(tenant)
    times = [g.ro_query(cypher, params).run_time_ms for _ in range(RUNS)]
    plan = client().connection.execute_command("GRAPH.PROFILE", tenant, _inline(cypher, params))
    plan = [p.decode() if isinstance(p, bytes) else p for p in plan]
    work = max(int(m.group(1)) for line in plan if (m := re.search(r"Records produced: (\d+)", line)))
    return statistics.median(times), work, plan


def _inline(cypher: str, params: dict) -> str:
    """GRAPH.PROFILE through the raw command takes a CYPHER prefix for parameters."""
    if not params:
        return cypher
    return "CYPHER " + " ".join(f"{k}={json.dumps(v)}" for k, v in params.items()) + " " + cypher


def catalogue(tenant: str) -> dict[str, tuple[str, dict]]:
    """The queries behind the tools, with real ids from the tenant's data."""
    g = graph(tenant)
    ticket, customer = g.ro_query(
        "MATCH (t:Ticket)-[:TOUCHES]->(:Hub)<-[:AFFECTS]-(:Decision) MATCH (t)-[:FROM]->(:Profile)-[:OF]->(c:Customer) "
        "RETURN t.id, c.id ORDER BY t.at DESC LIMIT 1").result_set[0]
    user, = g.ro_query("MATCH (u:User {role: 'agent'})-[:MEMBER_OF]->(:Team)-[:COVERS]->(:Region)<-[:IN]-(:Customer {id: $c}) "
                       "RETURN u.id LIMIT 1", {"c": customer}).result_set[0]
    hub, = g.ro_query("MATCH (:Ticket {id: $t})-[:TOUCHES]->(h:Hub)<-[:AFFECTS]-(:Decision) RETURN h.id LIMIT 1",
                      {"t": ticket}).result_set[0]
    decision, = g.ro_query("MATCH (d:Decision)-[:AFFECTS]->(:Hub {id: $h}) RETURN d.id ORDER BY d.made_at LIMIT 1",
                           {"h": hub}).result_set[0]
    now, = g.ro_query("MATCH (m:Meta {id: 'clock'}) RETURN m.now").result_set[0]
    return {
        "permission: team covers customer's region": (
            "MATCH (u:User {id: $u}), (c:Customer {id: $c}) WITH u, c "
            "MATCH (u)-[:MEMBER_OF]->(t:Team)-[:COVERS]->(r:Region)<-[:IN]-(c) RETURN t.id, r.id LIMIT 1",
            {"u": user, "c": customer}) if AFTER else (
            "MATCH (u:User {id: $u})-[:MEMBER_OF]->(t:Team)-[:COVERS]->(r:Region)<-[:IN]-(c:Customer {id: $c}) "
            "RETURN t.id, r.id LIMIT 1", {"u": user, "c": customer}),
        "resolve customer from a ticket": (
            "MATCH (:Ticket {id: $r})-[:FROM]->(:Profile)-[:OF]->(c:Customer) RETURN c.id", {"r": ticket}),
        "trace: orders with items and batches": (
            "MATCH (c:Customer {id: $c})<-[:OF]-(p:Profile)-[:PLACED]->(o:Order) "
            "OPTIONAL MATCH (o)-[:USED]->(k:Coupon) "
            "OPTIONAL MATCH (o)-[:HAS]->(l:LineItem)-[:OF]->(pr:Product) OPTIONAL MATCH (l)-[:FROM]->(b:Batch) "
            "RETURN o.id, o.placed_at, o.status, o.total, o.currency, k.id, "
            "collect({sku: pr.id, title: pr.title, batch: b.id, price: l.price}), p.id", {"c": customer}),
        "trace: parcels and courier scans": (
            "MATCH (c:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)-[:SHIPPED_AS]->(s:Shipment) "
            "OPTIONAL MATCH (s)-[:VIA]->(k:Courier) "
            "OPTIONAL MATCH (sc:Scan)-[:FOR]->(s) OPTIONAL MATCH (sc)-[:AT]->(h:Hub) "
            "WITH o, s, k, sc, h ORDER BY sc.at "
            "RETURN o.id, s.id, k.id, s.promised_at, collect({at: sc.at, hub: h.id, status: sc.status, "
            "late_hours: sc.late_hours})", {"c": customer}),
        "trace: tickets": (
            "MATCH (c:Customer {id: $c})<-[:OF]-(p:Profile)<-[:FROM]-(t:Ticket) "
            "OPTIONAL MATCH (t)-[:ABOUT]->(o:Order) OPTIONAL MATCH (t)-[:HANDLED_BY]->(u:User) "
            "OPTIONAL MATCH (t)-[:IN]->(q:Queue) "
            "RETURN t.id, t.at, t.channel, t.status, t.issue_type, t.summary_clean, o.id, u.id, p.id, q.id",
            {"c": customer}),
        "related issues via the same hub/courier/batch": (
            "MATCH (t:Ticket {id: $t})-[:TOUCHES]->(x)<-[:TOUCHES]-(other:Ticket) "
            "WHERE other.at >= $since AND other <> t "
            "RETURN labels(x)[0], x.id, count(other), "
            "sum(CASE WHEN other.issue_type = t.issue_type THEN 1 ELSE 0 END) ORDER BY count(other) DESC",
            {"t": ticket, "since": now - 7 * 86400}),
        "decisions behind a hub, with evidence": (
            "MATCH (d:Decision)-[:AFFECTS]->(h:Hub {id: $h}) OPTIONAL MATCH (d)-[:OWNED_BY]->(u:User) "
            "OPTIONAL MATCH (d)-[:RESTS_ON]->(a:Assumption) OPTIONAL MATCH (e:Evidence)-[:TESTS]->(a) "
            "WITH d, u, a, e ORDER BY e.window_end DESC WITH d, u, a, collect(e)[0] AS latest "
            "OPTIONAL MATCH (other:Decision)-[b:BREAKS]->(a) "
            "RETURN d.id, d.title, d.made_at, d.chose_kind, u.id, "
            "collect({assumption: a.id, status: a.status, value: latest.value, linked: other.id, basis: b.basis})",
            {"h": hub}),
        "impact: customers waiting on parcels at the hub": (
            "MATCH (s:Shipment) WHERE s.last_hub IN $hubs AND s.status IN ['in_transit', 'delayed'] "
            "MATCH (s)<-[:SHIPPED_AS]-(o:Order)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) "
            "OPTIONAL MATCH (c)<-[:OF]-(:Profile)<-[:FROM]-(t:Ticket) WHERE t.status <> 'solved' "
            "RETURN c.id, c.tier, sum(DISTINCT o.total) AS value, collect(DISTINCT o.id), count(DISTINCT t), "
            "max(s.late_hours) ORDER BY value DESC", {"hubs": [hub]}),
        "keystone decisions (PageRank)": (
            "CALL algo.pageRank('Decision', 'BUILDS_ON') YIELD node, score RETURN node.id, score ORDER BY score DESC", {}),
        "approver up the reporting line (SPpaths)": (
            "MATCH (a:User {id: $u}) MATCH (b:User) WHERE b.refund_limit >= $amt "
            "CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['REPORTS_TO'], relDirection: 'outgoing', "
            "pathCount: 1}) YIELD path RETURN b.id, length(path) ORDER BY length(path) LIMIT 1",
            {"u": user, "amt": 300}),
        "choke points (betweenness)": (
            "CALL algo.betweenness({nodeLabels: ['Hub'], relationshipTypes: ['ROUTES_TO'], samplingSize: 100, "
            "samplingSeed: 42}) YIELD node, score RETURN node.id, score ORDER BY score DESC LIMIT 3", {}),
        "assumption check: courier on-time at a hub": (
            ("MATCH (sc:Scan) WHERE sc.at >= $start AND sc.at < $end AND sc.status IN ['in_transit', 'delayed'] "
             "MATCH (sc)-[:AT]->(:Hub {id: $hub}), (sc)-[:FOR]->(:Shipment)-[:VIA]->(:Courier) " if AFTER else
             "MATCH (sc:Scan)-[:AT]->(:Hub {id: $hub}), (sc)-[:FOR]->(:Shipment)-[:VIA]->(:Courier) "
             "WHERE sc.at >= $start AND sc.at < $end AND sc.status IN ['in_transit', 'delayed'] ") +
            "RETURN count(sc), sum(CASE WHEN coalesce(sc.late_hours, 0) = 0 THEN 1 ELSE 0 END)",
            {"hub": hub, "start": now - 7 * 86400, "end": now}),
        "inbox: newest tickets this person may see": (
            "MATCH (:User {id: $u})-[:MEMBER_OF]->(:Team)-[:COVERS]->(:Region)<-[:IN]-(c:Customer) "
            "MATCH (c)<-[:OF]-(:Profile)<-[:FROM]-(t:Ticket) OPTIONAL MATCH (t)-[:IN]->(q:Queue) "
            "RETURN t.id, t.at, t.issue_type, t.status, t.summary_clean, c.id, c.region, q.id ORDER BY t.at DESC LIMIT 40",
            {"u": user}) if AFTER else (
            "MATCH (t:Ticket)-[:FROM]->(:Profile)-[:OF]->(c:Customer) OPTIONAL MATCH (t)-[:IN]->(q:Queue) "
            "RETURN t.id, t.at, t.issue_type, t.status, t.summary_clean, c.id, c.region, q.id ORDER BY t.at DESC LIMIT 400", {}),
        "full-text ticket search": (
            "CALL db.idx.fulltext.queryNodes('Ticket', $q) YIELD node, score "
            "MATCH (node)-[:FROM]->(:Profile)-[:OF]->(c:Customer) RETURN node.id, c.id, score ORDER BY score DESC LIMIT 50",
            {"q": "late"}),
    }


def run(tenant: str, label: str) -> list[dict]:
    rows = []
    for name, (cypher, params) in catalogue(tenant).items():
        ms, work, plan = profile(tenant, cypher, params)
        rows.append({"query": name, "median_ms": round(ms, 3), "max_rows_in_a_step": work, "plan": plan})
    DOCS.mkdir(exist_ok=True)
    (DOCS / f"perf-{tenant}-{label}.json").write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    tenant, label = (sys.argv + ["northwind", "before"])[1:3]
    AFTER = label.startswith("after")
    for r in run(tenant, label):
        print(f"{r['median_ms']:8.3f} ms  {r['max_rows_in_a_step']:6d} rows  {r['query']}")
