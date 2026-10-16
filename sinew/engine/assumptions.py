"""Machine-checkable assumptions (ENGINE.md §5c) and the evaluator that tests them against the graph.

An assumption is only accepted if it names a metric we can compute, a scope, an operator, a threshold
and a window. The evaluator writes Evidence nodes; a failing check marks the assumption broken.
Then one rule links other decisions to the break: a decision that AFFECTS the same hub and was active
during the evidence window. That link is an overlap in the data, never a claim of cause.
"""

import time

from falkordb import Graph

from sinew.db import graph

DAY = 86_400
MIN_SAMPLE = 10  # fewer observations than this: no evidence either way


def courier_on_time_rate(g: Graph, a: dict, start: int, end: int):
    """Share of scans at the hub, for the courier's shipments, that were not late."""
    total, on_time = g.ro_query(
        "MATCH (sc:Scan)-[:AT]->(:Hub {id: $hub}), (sc)-[:FOR]->(:Shipment)-[:VIA]->(:Courier {id: $courier}) "
        "WHERE sc.at >= $start AND sc.at < $end "
        "RETURN count(sc), sum(CASE WHEN coalesce(sc.late_hours, 0) = 0 THEN 1 ELSE 0 END)",
        {"hub": a["scope_hub"], "courier": a["scope_courier"], "start": start, "end": end},
    ).result_set[0]
    return (on_time / total, total) if total >= MIN_SAMPLE else (None, total)


def hub_load_ratio(g: Graph, a: dict, start: int, end: int):
    """Busiest day's scan count at the hub divided by its daily capacity."""
    rows = g.ro_query(
        "MATCH (sc:Scan)-[:AT]->(h:Hub {id: $hub}) WHERE sc.at >= $start AND sc.at < $end "
        "WITH h, sc.at / $day AS d, count(sc) AS n RETURN h.capacity, max(n), sum(n)",
        {"hub": a["scope_hub"], "start": start, "end": end, "day": DAY},
    ).result_set
    if not rows or rows[0][0] in (None, 0) or (rows[0][2] or 0) < MIN_SAMPLE:
        return None, (rows[0][2] if rows else 0) or 0
    capacity, busiest, total = rows[0]
    return busiest / capacity, total


METRICS = {
    "courier_on_time_rate": (courier_on_time_rate, {"scope_hub", "scope_courier"}),
    "hub_load_ratio": (hub_load_ratio, {"scope_hub"}),
}
OPS = {">=": lambda v, t: v >= t, "<=": lambda v, t: v <= t}


def check_shape(a: dict) -> str | None:
    """Why an assumption can't be machine-checked, or None if it can."""
    if a.get("metric") not in METRICS:
        return f"unknown metric {a.get('metric')!r}; known: {sorted(METRICS)}"
    if a.get("op") not in OPS:
        return "op must be >= or <="
    if not isinstance(a.get("threshold"), (int, float)) or not isinstance(a.get("window_days"), int):
        return "threshold must be a number and window_days a whole number"
    missing = METRICS[a["metric"]][1] - {k for k, v in a.items() if v}
    if missing:
        return f"metric {a['metric']} needs scope {sorted(missing)}"
    return None


def evaluate(tenant: str, now: int | None = None) -> list[dict]:
    """Check every active assumption over its window ending at `now`. Safe to rerun: one Evidence per day."""
    g = graph(tenant)
    now = now or int(time.time())
    out = []
    rows = g.ro_query(
        "MATCH (d:Decision)-[:RESTS_ON]->(a:Assumption) WHERE coalesce(d.status, 'active') = 'active' "
        "RETURN a.id, a.metric, a.op, a.threshold, a.window_days, a.scope_hub, a.scope_courier, d.id"
    ).result_set
    for aid, metric, op, threshold, window_days, hub, courier, decision_id in rows:
        a = {"scope_hub": hub, "scope_courier": courier}
        start = now - window_days * DAY
        value, sample = METRICS[metric][0](g, a, start, now)
        if value is None:
            out.append({"assumption": aid, "result": "insufficient data", "sample": sample})
            continue
        holds = OPS[op](value, threshold)
        evidence_id = f"ev:{aid}:{now // DAY}"
        g.query(
            "MATCH (a:Assumption {id: $aid}) MERGE (e:Evidence {id: $eid}) "
            "SET e.metric = $metric, e.value = $value, e.sample = $sample, e.window_start = $start, "
            "    e.window_end = $end, e.holds = $holds "
            "MERGE (e)-[:TESTS]->(a)",
            {"aid": aid, "eid": evidence_id, "metric": metric, "value": round(value, 4), "sample": sample,
             "start": start, "end": now, "holds": holds},
        )
        if holds:
            g.query("MATCH (a:Assumption {id: $aid}) SET a.status = 'holding', a.checked_at = $now",
                    {"aid": aid, "now": now})
        else:
            g.query(
                "MATCH (a:Assumption {id: $aid}), (e:Evidence {id: $eid}) "
                "SET a.status = 'broken', a.checked_at = $now, a.broken_at = coalesce(a.broken_at, $now) "
                "MERGE (e)-[:CONTRADICTS]->(a)",
                {"aid": aid, "eid": evidence_id, "now": now},
            )
            _link_overlapping_decisions(g, aid, decision_id, evidence_id, start, now)
        out.append({"assumption": aid, "value": round(value, 4), "holds": holds, "sample": sample})
    return out


def _link_overlapping_decisions(g: Graph, aid: str, own_decision: str, evidence_id: str, start: int, end: int):
    """Other decisions that touch the same hub and were live during the window get a BREAKS link."""
    g.query(
        "MATCH (a:Assumption {id: $aid})-[:ABOUT]->(h:Hub) "
        "MATCH (d:Decision)-[:AFFECTS]->(h) WHERE d.id <> $own AND d.made_at <= $end "
        "OPTIONAL MATCH (d)-[:CHOSE]->(k:Campaign) "
        "WITH a, d, k WHERE k IS NULL OR (k.starts < $end AND k.ends >= $start) "
        "MERGE (d)-[r:BREAKS]->(a) SET r.evidence = $eid, "
        "  r.basis = CASE WHEN k IS NULL THEN 'decision affects this hub and was live during the window' "
        "               ELSE 'campaign ' + k.id + \" ran in this hub's region during the window\" END",
        {"aid": aid, "own": own_decision, "eid": evidence_id, "start": start, "end": end},
    )
