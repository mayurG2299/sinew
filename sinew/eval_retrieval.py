"""Retrieval accuracy, no AI: random questions are routed to graph walks, run as the person asking (through the
same tool server and permission checks the AI uses), and the returned data is checked against the truth from
independent Cypher.

    SINEW_LOCAL=1 uv run python -m sinew.eval_retrieval [seed] [rounds]

It tests what the AI would be given. If the right facts aren't in what the graph returns, no wording can fix it.
"""

import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path

from sinew.db import graph
from sinew.eval import has_amount
from sinew.tools.trace import clock

DAY = 86_400


def q(tenant, cypher, **p):
    return graph(tenant).ro_query(cypher, p).result_set


async def retrieve(tenant: str, user: str, question: str) -> list[dict]:
    """Exactly what the app does before the AI: the analysis layer's walks, as this person."""
    from sinew.brain import analyse
    _, per_part, _ = await analyse(tenant, user, question)
    seen, out = set(), []
    for got in per_part:
        for r in got:
            key = json.dumps(r.get("_call") or r, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                out.append(r)
    return out


def blob(results) -> str:
    return json.dumps(results, default=str)


def refused(results, value=None) -> bool:
    b = blob(results)
    return any(r.get("outcome") == "not_permitted" for r in results) and (value is None or not has_amount(b, value))


def cases(seed: int, rounds: int, T: str = "northwind") -> list[dict]:
    rng = random.Random(seed)
    now = clock(T)
    out = []
    orders = q(T, "MATCH (c:Customer)<-[:OF]-(:Profile)-[:PLACED]->(o:Order) RETURN o.id, c.id, c.region")
    agents = {"west": "u-agent-w1", "north": "u-agent-n1", "south": "u-agent-s1"}
    for _ in range(rounds):
        oid, cid, region = rng.choice(orders)
        n = "#" + oid[2:]
        total = q(T, "MATCH (o:Order {id: $o}) RETURN o.total", o=oid)[0][0]
        refunded = round(q(T, "MATCH (:Order {id: $o})<-[:FOR]-(r:Refund {status: 'issued'}) RETURN sum(r.amount)", o=oid)[0][0] or 0, 2)
        delivered = bool(q(T, "MATCH (:Order {id: $o})-[:SHIPPED_AS]->()<-[:FOR]-(:Scan {status: 'delivered'}) RETURN 1", o=oid))
        hubs = sorted({h for h, in q(T, "MATCH (:Order {id: $o})-[:SHIPPED_AS]->()<-[:FOR]-(:Scan)-[:AT]->(h:Hub) RETURN h.id", o=oid)})
        n_orders = q(T, "MATCH (:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order) RETURN count(o)", c=cid)[0][0]
        owner = agents[region]
        other = rng.choice([a for r, a in agents.items() if r != region])

        def data(res):
            return next((r["data"] for r in res if r.get("tool") == "order_detail" and r.get("outcome") == "answered_path"), None)
        out += [
            {"who": owner, "q": f"What was the total of order {n}?", "expect": f"total {total}",
             "ok": lambda res, t=total: (d := data(res)) is not None and d["total"] == t},
            {"who": owner, "q": f"Has order {n} been delivered?", "expect": f"delivered={delivered}",
             "ok": lambda res, x=delivered: (d := data(res)) is not None and d["delivery"]["delivered"] == x},
            {"who": owner, "q": f"Was order {n} refunded?", "expect": f"refunded {refunded}",
             "ok": lambda res, x=refunded: (d := data(res)) is not None and d["refunded_total"] == x},
            {"who": owner, "q": f"Which hubs did order {n} go through?", "expect": ", ".join(hubs),
             "ok": lambda res, x=hubs: (d := data(res)) is not None and sorted({s["hub"] for s in d["delivery"]["scans"]}) == x},
            {"who": owner, "q": f"How many orders has the customer who ordered {n} placed in total?", "expect": str(n_orders),
             "ok": lambda res, x=n_orders: (d := data(res)) is not None and d["customer_orders_in_total"] == x},
            {"who": other, "q": f"What is happening with order {n}?", "expect": "refused (other region)",
             "ok": lambda res, t=total: refused(res, t)},
            {"who": "u-marketing", "q": f"What was the total of order {n}?", "expect": "refused (no support area)",
             "ok": lambda res, t=total: refused(res, t)},
        ]
    # company-level facts
    tickets = q(T, "MATCH (t:Ticket) WHERE t.at >= $s AND t.at < $e RETURN count(t)", s=now - 7 * DAY, e=now)[0][0]
    revenue = round(q(T, "MATCH (o:Order) WHERE o.placed_at >= $s AND o.placed_at < $e RETURN sum(o.total)", s=now - 7 * DAY, e=now)[0][0], 2)
    ev = q(T, "MATCH (:Assumption {id: 'as-courier-y-ontime'})<-[:TESTS]-(e:Evidence) RETURN e.value ORDER BY e.window_end DESC LIMIT 1")[0][0]
    waiting = q(T, "MATCH (s:Shipment {last_hub: 'hub-w2'}) WHERE s.status IN ['in_transit', 'delayed'] "
                   "MATCH (s)<-[:SHIPPED_AS]-(:Order)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) RETURN count(DISTINCT c)")[0][0]
    days = round((q(T, "MATCH (c:Campaign {id: 'winter25'}) RETURN c.starts")[0][0] - now) / DAY)
    cost_y = q(T, "MATCH (k:CostLine)-[:FOR]->(:Courier {id: 'courier-y'}) RETURN k.amount")[0][0]
    out += [
        {"who": "u-lead-west", "q": "How many support tickets did we get this week?", "expect": str(tickets),
         "ok": lambda res, x=tickets: any((r.get("data") or {}).get("support", {}).get("tickets_this_week") == x for r in res)},
        {"who": "u-cmo", "q": "What was our revenue this week?", "expect": f"${revenue:,.2f}",
         "ok": lambda res, x=revenue: has_amount(blob(res), x)},
        {"who": "u-marketing", "q": "What was our revenue this week?", "expect": "no revenue figure",
         "ok": lambda res, x=revenue: not has_amount(blob(res), x)},
        {"who": "u-logistics", "q": "What is Courier Y's on-time rate at Hub W2 this week?", "expect": f"{round(ev * 100)}%",
         "ok": lambda res, x=ev: f"{round(x * 100)}%" in blob(res)},
        {"who": "u-logistics", "q": "How many customers are still waiting on parcels at Hub W2?", "expect": str(waiting),
         "ok": lambda res, x=waiting: any((r.get("data") or {}).get("customers_waiting") == x for r in res)},
        {"who": "u-marketing", "q": "How many days until the Winter Sale starts?", "expect": str(days),
         "ok": lambda res, x=days: any(((r.get("data") or {}).get("campaign") or {}).get("starts_in_days") == x for r in res)},
        {"who": "u-cmo", "q": "What does Courier Y cost per parcel?", "expect": f"${cost_y:.2f}",
         "ok": lambda res, x=cost_y: has_amount(blob(res), x)},
        {"who": "u-marketing", "q": "What does Courier Y cost per parcel?", "expect": "no cost figure",
         "ok": lambda res, x=cost_y: not has_amount(blob(res), x)},
        {"who": "u-agent-w1", "q": "Who has to approve a $300 refund?", "expect": "team leads ... up to $500",
         "ok": lambda res: "Team leads approve up to $500" in blob(res)},
        {"who": "u-agent-w1", "q": "What is our office leave policy?", "expect": "no leave document",
         "ok": lambda res: "leave" not in blob(res).lower() or all(r.get("outcome") != "answered_path" for r in res)},
        {"who": "u-logistics", "q": "Why are complaints up this week?", "expect": "Hub W2 -> Courier Y decision at 77%",
         "ok": lambda res: "hub-w2" in blob(res) and "dec-courier-y" in blob(res) and "0.7658" in blob(res)},
        {"who": "u-contractor-1", "q": "Why are complaints up this week?", "expect": "refused (no operations area)",
         "ok": lambda res: refused(res) and "dec-courier-y" not in blob(res)},
        {"who": "u-logistics", "q": "Tell me about the courier Y switch", "expect": "the Courier Y decision, 77% vs 90%",
         "ok": lambda res: "Switch west region deliveries to Courier Y" in blob(res) and "77%" in blob(res)},
    ]
    return out


async def main(seed: int, rounds: int, tenant: str = "northwind") -> list[dict]:
    res = []
    for c in cases(seed, rounds, tenant):
        got = await retrieve(tenant, c["who"], c["q"])
        ok = bool(c["ok"](got))
        res.append({**{k: c[k] for k in ("who", "q", "expect")}, "ok": ok,
                    "tools": [r.get("tool") for r in got], "size": len(blob(got)), "got": blob(got)[:400]})
    return res


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else int(time.time()) % 100000
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    t0 = time.time()
    res = asyncio.run(main(seed, rounds))
    bad = [r for r in res if not r["ok"]]
    print(f"{len(res) - len(bad)}/{len(res)} passed, seed {seed}, {time.time() - t0:.1f}s, "
          f"median retrieved {sorted(r['size'] for r in res)[len(res) // 2]} chars")
    for r in bad[:20]:
        print(f"FAIL {r['who']}: {r['q']}  expected {r['expect']}  tools {r['tools']}\n     got {r['got'][:300]}")
    Path(__file__).resolve().parents[1].joinpath("docs", f"eval-retrieval-{seed}.json").write_text(json.dumps(res, indent=1))
