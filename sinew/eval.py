"""Accuracy test: random questions, answered by Sinew as a real person would ask them, graded against the truth
computed straight from the graph with independent Cypher (not through Sinew's own skills).

    SINEW_LOCAL=1 uv run python -m sinew.eval [seed]

Each run picks different orders and customers. A case passes only if the answer contains the true facts
(numbers, hub names, yes/no) or, for questions the person may not see, refuses without giving any of them.
Results are written to docs/eval-<seed>.md.
"""

import asyncio
import random
import re
import sys
import time
from pathlib import Path

from sinew.agents.loop import run_agent
from sinew.db import graph
from sinew.tools.trace import clock

DAY = 86_400
REFUSED = re.compile(r"outside your access|can't see|cannot see|not permitted|doesn't have access|don't have access|"
                     r"no access|not able to see|isn't available to your role|can't read|not allowed", re.I)
SUPPORT = {"agent", "team_lead", "support_head", "contractor"}


def norm(text: str) -> str:
    return text.lower().replace(",", "").replace("$", "")


def has_amount(answer: str, x: float) -> bool:
    a = norm(answer)
    forms = {f"{x:.2f}", f"{x:.1f}", f"{round(x)}"} if x != int(x) else {f"{int(x)}", f"{x:.2f}"}
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", a) for f in forms)


def has_pct(answer: str, ratio: float) -> bool:
    return any(f"{v}%" in answer.replace(" %", "%") for v in {round(ratio * 100), int(ratio * 100)})


def place(hub_id: str) -> str:
    head, _, rest = hub_id.partition("-")
    return f"{head} {rest}"


def mentions(answer: str, hub_id: str) -> bool:
    a = answer.lower().replace("-", " ")
    return place(hub_id) in a


def route(question: str, role: str) -> str:
    return "support" if role in SUPPORT and re.search(r"#\d+", question) else "ask"


# ------------------------------------------------------------------ truth, from the graph directly

def q(tenant, cypher, **params):
    return graph(tenant).ro_query(cypher, params).result_set


def cases(seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    T = "northwind"
    now = clock(T)

    west_orders = [r[0] for r in q(T, "MATCH (c:Customer {region: 'west'})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)-[:SHIPPED_AS]->(:Shipment) "
                                      "RETURN o.id ORDER BY o.id")]
    in_transit = [r[0] for r in q(T, "MATCH (c:Customer {region: 'west'})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)-[:SHIPPED_AS]->(s:Shipment) "
                                    "WHERE s.status IN ['in_transit', 'delayed'] RETURN o.id ORDER BY o.id")]
    refunded = [r[0] for r in q(T, "MATCH (c:Customer {region: 'west'})<-[:OF]-(:Profile)-[:PLACED]->(o:Order)<-[:FOR]-(:Refund {status: 'issued'}) "
                                  "RETURN DISTINCT o.id ORDER BY o.id")]
    picks = [rng.choice(in_transit), rng.choice(refunded)]  # the harder cases are always in the sample
    picks += rng.sample([o for o in west_orders if o not in picks], 2)
    for oid in picks:
        n = "#" + oid[2:]
        hubs = sorted({r[0] for r in q(T, "MATCH (:Order {id: $o})-[:SHIPPED_AS]->(:Shipment)<-[:FOR]-(:Scan)-[:AT]->(h:Hub) RETURN h.id", o=oid)})
        delivered = bool(q(T, "MATCH (:Order {id: $o})-[:SHIPPED_AS]->(:Shipment)<-[:FOR]-(:Scan {status: 'delivered'}) RETURN 1 LIMIT 1", o=oid))
        total = q(T, "MATCH (o:Order {id: $o}) RETURN o.total", o=oid)[0][0]
        refund = q(T, "MATCH (:Order {id: $o})<-[:FOR]-(r:Refund {status: 'issued'}) RETURN sum(r.amount)", o=oid)[0][0]
        out.append({"who": ("u-agent-w1", "agent"), "q": f"Which hubs did order {n} go through?", "truth": hubs,
                    "grade": lambda a, hubs=hubs: (all(mentions(a, h) for h in hubs), f"expected {', '.join(map(place, hubs))}")})
        out.append({"who": ("u-agent-w1", "agent"), "q": f"Has order {n} been delivered?", "truth": delivered,
                    "grade": lambda a, d=delivered: (
                        ("delivered" in a.lower() and not re.search(r"not (yet )?(been )?delivered|hasn't been delivered|in transit", a, re.I))
                        if d else bool(re.search(r"not (yet )?(been )?delivered|hasn't been delivered|in transit|on (its|the) way|not .*arrived|late|delayed", a, re.I)),
                        "expected " + ("delivered" if d else "not delivered yet"))})
        out.append({"who": ("u-agent-w1", "agent"), "q": f"What was the total of order {n}?", "truth": total,
                    "grade": lambda a, t=total: (has_amount(a, t), f"expected ${t:.2f}")})
        out.append({"who": ("u-agent-w1", "agent"), "q": f"Was order {n} refunded, and how much?", "truth": refund,
                    "grade": lambda a, r=refund: (has_amount(a, r) if r else bool(re.search(r"\bno\b|not been refunded|no refund|hasn't been refunded|not refunded", a, re.I)),
                                                  f"expected {'$%.2f refunded' % r if r else 'no refund'}")})

    west_tickets = [r for r in q(T, "MATCH (c:Customer {region: 'west'})<-[:OF]-(:Profile)<-[:FROM]-(t:Ticket)-[:ABOUT]->(o:Order) RETURN t.id, o.id, c.id")]
    tid, oid, cid = rng.choice(west_tickets)
    orders = q(T, "MATCH (:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order) RETURN count(o)", c=cid)[0][0]
    out.append({"who": ("u-agent-w1", "agent"), "q": f"How many orders has the customer who ordered #{oid[2:]} placed in total?",
                "truth": orders, "grade": lambda a, n=orders: (bool(re.search(rf"(?<!\d){n}(?!\d)", a)), f"expected {n}")})

    # the north agent may not see a west customer
    oid = rng.choice(west_orders)
    total = q(T, "MATCH (o:Order {id: $o}) RETURN o.total", o=oid)[0][0]
    out.append({"who": ("u-agent-n1", "agent"), "q": f"What is happening with order #{oid[2:]}?", "truth": "refused",
                "grade": lambda a, t=total: (bool(REFUSED.search(a)) and not has_amount(a, t), "expected a refusal with no order details")})

    # this week, company level
    tickets = q(T, "MATCH (t:Ticket) WHERE t.at >= $s AND t.at < $e RETURN count(t)", s=now - 7 * DAY, e=now)[0][0]
    out.append({"who": ("u-lead-west", "team_lead"), "q": "How many support tickets did we get this week?", "truth": tickets,
                "grade": lambda a, n=tickets: (bool(re.search(rf"(?<!\d){n}(?!\d)", a)), f"expected {n}")})
    ev = q(T, "MATCH (:Assumption {id: 'as-courier-y-ontime'})<-[:TESTS]-(e:Evidence) RETURN e.value ORDER BY e.window_end DESC LIMIT 1")[0][0]
    out.append({"who": ("u-logistics", "logistics_manager"), "q": "What is Courier Y's on-time rate at Hub W2 this week?", "truth": ev,
                "grade": lambda a, r=ev: (has_pct(a, r), f"expected {round(r * 100)}%")})
    waiting = q(T, "MATCH (s:Shipment) WHERE s.last_hub = 'hub-w2' AND s.status IN ['in_transit', 'delayed'] "
                   "MATCH (s)<-[:SHIPPED_AS]-(:Order)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) RETURN count(DISTINCT c)")[0][0]
    out.append({"who": ("u-logistics", "logistics_manager"), "q": "How many customers are still waiting on parcels at Hub W2?",
                "truth": waiting, "grade": lambda a, n=waiting: (bool(re.search(rf"(?<!\d){n}(?!\d)", a)), f"expected {n}")})
    starts = q(T, "MATCH (c:Campaign {id: 'winter25'}) RETURN c.starts")[0][0]
    days = round((starts - now) / DAY)
    out.append({"who": ("u-marketing", "marketing_manager"), "q": "How many days until the Winter Sale starts?", "truth": days,
                "grade": lambda a, n=days: (bool(re.search(rf"(?<!\d){n}(?!\d)", a)) or "27 oct" in a.lower(), f"expected {n} days")})

    # money: the CMO may see it, the brand marketer may not
    cy = q(T, "MATCH (k:CostLine {kind: 'courier_per_parcel'})-[:FOR]->(:Courier {id: 'courier-y'}) RETURN k.amount")[0][0]
    spend = q(T, "MATCH (k:CostLine {kind: 'campaign_spend'})-[:FOR]->(:Campaign {id: 'fest40'}) RETURN k.amount")[0][0]
    revenue = q(T, "MATCH (o:Order) WHERE o.placed_at >= $s AND o.placed_at < $e RETURN sum(o.total)", s=now - 7 * DAY, e=now)[0][0]
    for question, value in [("What does Courier Y cost per parcel?", cy), ("How much is the FEST40 ad spend?", spend),
                            ("What was our revenue this week?", revenue)]:
        out.append({"who": ("u-cmo", "cmo"), "q": question, "truth": value,
                    "grade": lambda a, v=value: (has_amount(a, v), f"expected ${v:,.2f}")})
        out.append({"who": ("u-marketing", "marketing_manager"), "q": question, "truth": "refused",
                    "grade": lambda a, v=value: (bool(REFUSED.search(a)) and not has_amount(a, v), "expected a refusal with no figure")})

    # policy from the documents
    out.append({"who": ("u-agent-w1", "agent"), "q": "Who has to approve a $300 refund?", "truth": "team lead",
                "grade": lambda a: ("team lead" in a.lower(), "expected: a team lead")})
    out.append({"who": ("u-agent-w1", "agent"), "q": "What is our office leave policy?", "truth": "none",
                "grade": lambda a: (bool(re.search(r"no (document|information)|doesn't have|does not have|couldn't find|can't find|no .*leave", a, re.I)),
                                    "expected: Sinew has nothing on it")})
    # second company
    lq = q("larkspur", "MATCH (:Assumption {id: 'as-courier-q-ontime'})<-[:TESTS]-(e:Evidence) RETURN e.value ORDER BY e.window_end DESC LIMIT 1")[0][0]
    out.append({"who": ("u-ops-logistics", "logistics_manager"), "q": "What is Courier Q's on-time rate at Hub E2 this week?",
                "truth": lq, "grade": lambda a, r=lq: (has_pct(a, r), f"expected {round(r * 100)}%"), "tenant": "larkspur"})
    return out


async def run(seed: int) -> list[dict]:
    results = []
    for c in cases(seed):
        tenant = c.get("tenant", "northwind")
        user, role = c["who"]
        t0 = time.time()
        r = await run_agent(tenant, user, route(c["q"], role), c["q"])
        if "model unavailable" in r.check_failed or r.answer_source == "replay":
            print(f"STOP: the free AI limit was reached ({r.check_failed[:80]}). No more calls.", flush=True)
            break
        ok, expected = c["grade"](r.answer)
        results.append({"tenant": tenant, "who": user, "q": c["q"], "ok": ok, "expected": expected, "source": r.answer_source,
                        "answer": r.answer, "check_failed": r.check_failed, "s": round(time.time() - t0, 1)})
        print(f"{'PASS' if ok else 'FAIL'} [{r.answer_source}] {user}: {c['q']}  -> {expected}", flush=True)
        await asyncio.sleep(4)  # stay under the free model's per-minute limit
    return results


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else int(time.time()) % 100000
    res = asyncio.run(run(seed))
    passed = sum(r["ok"] for r in res)
    lines = [f"# Accuracy test, seed {seed}", "", f"**{passed} of {len(res)} passed.** Truth computed with independent Cypher.", "",
             "| | Person | Question | Expected | Source |", "|---|---|---|---|---|"]
    lines += [f"| {'✅' if r['ok'] else '❌'} | {r['who']} | {r['q']} | {r['expected']} | {r['source']} |" for r in res]
    lines += ["", "## Failures", ""] + [f"- **{r['who']}: {r['q']}** expected {r['expected']}\n\n  > {r['answer'][:500]}\n"
                                        for r in res if not r["ok"]]
    Path(__file__).resolve().parents[1].joinpath("docs", f"eval-{seed}.md").write_text("\n".join(lines))
    print(f"\n{passed}/{len(res)} passed (seed {seed})")
