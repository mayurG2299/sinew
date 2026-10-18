"""The analysis layer: understand the question, break it down, walk the graph, reconcile, and only then write.

    understand(question)  -> Plan: who is asking, the things named (linked to real graph nodes), the time window,
                             and the parts of the question, each with its intent
    walks(plan)           -> for each part, the graph walks that answer it, starting at the nodes it names
    traverse(...)         -> runs them as the person asking (same tool server, same permission checks), plus
                             memory: earlier findings about the same things
    reconcile(...)        -> one fact sheet: facts per part with their scope and source, gaps named
                             (no data vs no access), scopes labelled where two figures could look like a
                             conflict, and recommendations that follow from the facts
    write(sheet)          -> a plain answer from the fact sheet alone; the AI rewrites it in better words
                             when it is available, and is checked against the same facts

Stages 1, 2 and 4 are deterministic and have their own tests; the AI is only ever the last step.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field

from mcp import Client

from sinew.db import graph
from sinew.mcp_server import build_server
from sinew.tools import guard
from sinew.tools.trace import clock

DAY = 86_400
GENERIC = {"courier", "cost", "costs", "deliveries", "delivery", "customers", "hub", "sale", "day", "the", "and",
           "west", "east", "region", "run", "off", "for", "with", "move", "home", "kitchen"}

INTENTS = [  # (intent, pattern) in the order they are reported
    ("personal_bulk", r"(list|all|every|export|download)\b.*\b(customers?|emails?|phone numbers?|addresses)\b"),
    ("attention", r"what happened|what'?s new|anything new|worry|needs? (my )?attention|should i know|update me|"
                  r"problems? this week|issues? this week|what'?s going on"),
    ("rank", r"\b(worst|best|most|least|top|biggest|slowest|fastest)\b|which (hub|courier|product|campaign)"),
    ("contact", r"\b(phone|email|e-mail|address|contact|call)\b"),
    ("why", r"\bwhy\b|what('s| is) behind|root cause|what caused|reason for"),
    ("verdict", r"safe to (launch|run|go|start)|should we (launch|run|go ahead)|ready (to|for) launch|go ahead with|"
                r"is it (ok|okay|fine|wise|a good idea)|can (it|we|the hub|hub \w+) (handle|cope|carry|take)|will it (hold|cope|work)"),
    ("what_to_do", r"what should (we|i) do|what (do|can) (we|i) do|what to do|recommend|next step|how (do|can) we fix|should we|"
                   r"taken care of|need(s)? to be (done|handled|taken care|checked)|things? (to|we need to) (do|watch|check|handle)|"
                   r"what (do )?(we|i) need|watch out|what could go wrong|\brisks?\b|pitfalls?|\bwhat if\b|"
                   r"\bif we (want to |were to |only |just )?(use|move|switch|stop|drop|end|keep|run|go|rely|continue)"),
    ("detail", r"\bmore (details?|info|information|about)\b|\bdetails?\b|elaborate|tell me more|know more|want more|go deeper|"
               r"break (it|that|this) down|in depth|explain (that|it|this)"),
    ("tickets", r"\b(open |unsolved |pending |those |these )?tickets\b|\bopen (ticket|complaint)s?\b"),
    ("capacity", r"capacity|headroom|spare room|overload(ed)?|how full|utili[sz]ation|over capacity|under capacity|\bbusy\b"),
    ("pulse", r"how is the company|how are we doing|state of the company|company doing|overview|summary|how('s| is) (it|business) going"),
    ("cost", r"\bcost|spend|budget|price|revenue|margin|money"),
    ("policy", r"polic|rule|how fast|who (can|has to|must|should) approve|allowed|contract|agreement|terms|guideline|"
               r"can i (refund|approve|give|offer)|am i allowed|my limit|limit for|refund limit|"
               r"standard|leave|process for|plan for|meeting notes|what did we (agree|decide)"),
    ("count", r"how many|how much|what('s| is) the (rate|number)|on-?time|percent|%"),
]


@dataclass
class Entity:
    kind: str      # Order, Hub, Courier, Campaign, Decision, Product, Batch, Region
    id: str
    label: str
    said: str      # the words in the question that named it


@dataclass
class Part:
    text: str
    intents: list[str]
    entities: list[Entity]


@dataclass
class Plan:
    question: str
    tenant: str
    user: str
    role: str
    areas: list[str]
    window: dict
    entities: list[Entity] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # names in the question that match nothing in the graph
    follow_up_to: str = ""  # the earlier question this one carries on from
    refund_limit: float = 0

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ 1. understand

_INDEX: dict[str, tuple[float, list[tuple[str, str, str, list[str]]]]] = {}


def _index(tenant: str) -> list[tuple[str, str, str, list[str]]]:
    """(kind, id, label, ways people say it) for everything a question can name; cached for a minute."""
    hit = _INDEX.get(tenant)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    g = graph(tenant)
    out = []
    for hid, in g.ro_query("MATCH (h:Hub) RETURN h.id").result_set:
        code = hid.split("-", 1)[1]
        out.append(("Hub", hid, f"Hub {code.upper()}", [f"hub {code}", f"hub-{code}", f"hub{code}"]))
    for cid, name in g.ro_query("MATCH (c:Courier) RETURN c.id, c.name").result_set:
        code = cid.split("-", 1)[1]
        out.append(("Courier", cid, f"Courier {code.upper()}", [f"courier {code}", cid]))
    for cid, name, coupons in g.ro_query("MATCH (c:Campaign) OPTIONAL MATCH (k:Coupon)-[:OF]->(c) "
                                         "RETURN c.id, c.name, collect(k.id)").result_set:
        out.append(("Campaign", cid, name, [cid, name.lower()] + [k.lower() for k in coupons]))
    for pid, title in g.ro_query("MATCH (p:Product) RETURN p.id, p.title").result_set:
        out.append(("Product", pid, title, [title.lower()]))
    for bid, in g.ro_query("MATCH (b:Batch) WHERE NOT b.id STARTS WITH 'b-' RETURN b.id").result_set:
        out.append(("Batch", bid, f"Batch {bid.upper()}", [f"batch {bid}", bid]))
    for rid, in g.ro_query("MATCH (r:Region) RETURN r.id").result_set:
        out.append(("Region", rid, rid.title(), [f"{rid} region", f"the {rid}", f"in {rid}"]))
    for did, title in g.ro_query("MATCH (d:Decision) RETURN d.id, d.title").result_set:
        out.append(("Decision", did, title, [did, title.lower()]))
    _INDEX[tenant] = (time.time(), out)
    return out


def _link(tenant: str, text: str) -> tuple[list[Entity], list[str]]:
    """The graph nodes a text names, and the names it uses that match nothing ("Hub Z9", "order #99999")."""
    t = " " + re.sub(r"[^a-z0-9#$.%\-\s]", " ", text.lower()) + " "
    found: list[Entity] = []
    seen = set()
    missing: list[str] = []

    def add(kind, nid, label, said):
        if nid not in seen:
            seen.add(nid)
            found.append(Entity(kind, nid, label, said))

    for m in re.finditer(r"\bt-(\d{4,6})\b", t):  # a ticket (the portal passes the one being handled)
        if graph(tenant).ro_query("MATCH (x:Ticket {id: $t}) RETURN 1", {"t": f"t-{m.group(1)}"}).result_set:
            add("Ticket", f"t-{m.group(1)}", "this ticket", m.group(0))
    for m in re.finditer(r"(?<![\w$.-])#?\s?(\d{4,6})(?![\w.%])", t):  # #4520, 4520, "ordr 4520" (not $300, 4.5%)
        n = m.group(1)
        if graph(tenant).ro_query("MATCH (o:Order {id: $o}) RETURN 1", {"o": f"o-{n}"}).result_set:
            add("Order", f"o-{n}", f"order #{n}", m.group(0).strip())
        elif re.search(rf"(#|order\w*\s*)\s?{n}", t):
            missing.append(f"order #{n}")
    for m in re.finditer(r"(?<![a-z0-9])(?:hub\s?-?)?([a-z])\s?(\d)(?![a-z0-9])", t):  # Hub W2, hub-w2, "W2"
        hid = f"hub-{m.group(1)}{m.group(2)}"
        if any(k == "Hub" and nid == hid for k, nid, _, _ in _index(tenant)):
            add("Hub", hid, f"Hub {m.group(1).upper()}{m.group(2)}", m.group(0).strip())
        elif m.group(0).strip().startswith("hub"):
            missing.append(f"Hub {m.group(1).upper()}{m.group(2)}")
    words = set(re.findall(r"[a-z0-9]{3,}", t))
    decisions = []
    for kind, nid, label, ways in _index(tenant):
        if kind == "Decision":
            decisions.append((nid, label))
            if any(f" {w} " in t for w in ways):
                add(kind, nid, label, label)
            continue
        for w in ways:
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", t):
                add(kind, nid, label, w)
                break
        else:
            if kind == "Product":  # "blenders", "the kettle": the first word of a product title, if only one has it
                first = ways[0].split()[0]
                same = [x for x in _index(tenant) if x[0] == "Product" and x[3][0].split()[0] == first]
                if len(first) >= 4 and len(same) == 1 and re.search(rf"(?<![a-z0-9]){re.escape(first)}s?(?![a-z0-9])", t):
                    add(kind, nid, label, first)
    title_words = {did: set(re.findall(r"[a-z0-9]{3,}", title.lower())) - GENERIC for did, title in decisions}
    for did, title in decisions:  # a decision named by its title words ("the courier y switch", "the backup courier")
        tw = title_words[did]
        hit = tw & words
        unique = {w for w in hit if len(w) >= 4 and sum(w in o for o in title_words.values()) == 1}
        if hit and (len(hit) >= 2 or unique or (len(tw) and len(hit) / len(tw) >= 0.6)):
            add("Decision", did, title, " ".join(sorted(hit)))
    return found, missing


def _window(text: str, now: int) -> dict:
    t = text.lower()
    m = re.search(r"last (\d{1,3}) days", t)
    if m:
        d = int(m.group(1))
    elif "today" in t:
        d = 1
    elif "yesterday" in t:
        return {"label": "yesterday", "start": now - 2 * DAY, "end": now - DAY, "days": 1}
    elif "this month" in t or "last month" in t or "30 days" in t:
        d = 30
    else:
        d = 7
    return {"label": {1: "today", 7: "this week", 30: "the last 30 days"}.get(d, f"the last {d} days"),
            "start": now - d * DAY, "end": now, "days": d}


def _intents(text: str, entities: list[Entity]) -> list[str]:
    t = text.lower()
    found = [name for name, pattern in INTENTS if re.search(pattern, t)]
    if entities and not {"why", "pulse"} & set(found):
        found.insert(0, "status")  # a named thing: tell me about it
    return found or ["status" if entities else "unknown"]


def _split(question: str) -> list[str]:
    """Break a question into parts that each ask for something different."""
    pieces = [p.strip(" ,;") for p in re.split(r"\?|;|\band (?=what|why|how|who|which|when|is|are|can|should)\b", question)]
    return [p for p in pieces if len(p) > 3] or [question]


def _topic(tenant: str, history):
    """What an earlier question was really about: the latest one that named something or asked something specific.
    A follow-up ("more details") never counts as the topic, so a chain of follow-ups keeps the original subject."""
    for h in reversed(history or []):
        ents = _link(tenant, h)[0]
        ints = _intents(h, ents)
        if ents or set(ints) & SPECIFIC:
            return h, ents, ints
    return None


def _is_follow_up(tenant: str, question: str, history) -> bool:
    """A short question that names nothing and asks for more ("more details", "why is that?", "and what about it?")
    carries on from the previous one."""
    if not history or len(question.split()) > 16:
        return False
    if _link(tenant, question)[0]:
        return False
    if _topic(tenant, history) is None:
        return False
    intents = _intents(question, [])
    return intents == ["unknown"] or "detail" in intents or len(question.split()) <= 4


def understand(tenant: str, user_id: str, question: str, history=()) -> Plan:
    v = guard.Viewer.load(tenant, user_id)
    now = clock(tenant)
    plan = Plan(question, tenant, user_id, v.role if v else "", v.areas if v else [], _window(question, now))
    plan.refund_limit = v.refund_limit if v else 0
    if not question.strip():
        return plan  # nothing asked
    if _is_follow_up(tenant, question, history):
        before, ents, before_intents = _topic(tenant, history)
        inherited = [i for i in before_intents if i not in ("unknown", "status", "detail")]
        own = [i for i in _intents(question, ents) if i not in ("unknown", "status")]
        plan.entities, plan.follow_up_to = ents, before
        plan.parts.append(Part(question, (own + [i for i in inherited if i not in own]) or ["status"], ents))
        return plan
    plan.entities, plan.missing = _link(tenant, question)
    for text in _split(question):
        ents = _link(tenant, text)[0] or ([] if len(_split(question)) > 1 else plan.entities)
        plan.parts.append(Part(text, _intents(text, ents), ents))
    # "...and what should we do?" or "...and what did it cost?" refers to what was named earlier in the question
    previous: list[Entity] = []
    for p in plan.parts:
        refers_back = re.search(r"\b(it|its|it's|that|this|they|them|their|those)\b", p.text.lower())
        if not p.entities and previous and (refers_back or p.intents in (["what_to_do"], ["unknown"])):
            p.entities = previous
            if "status" not in p.intents and not {"why", "pulse"} & set(p.intents):
                p.intents = ["status"] + p.intents
        previous = p.entities or previous
    return plan


# ------------------------------------------------------------------ 2. walks for each part

def walks(plan: Plan) -> list[list[tuple[str, dict]]]:
    """For each part, the graph walks that answer it, starting at what it names."""
    out = []
    for p in plan.parts:
        calls: list[tuple[str, dict]] = []
        for e in p.entities:
            if e.kind == "Ticket":
                calls += [("customer_trace", {"customer": e.id}), ("open_loops", {"customer": e.id}),
                          ("related_issues", {"ticket_id": e.id})]
            elif e.kind == "Order":
                calls.append(("order_detail", {"order": "#" + e.id[2:]}))
            elif e.kind == "Hub":
                calls.append(("hub_status", {"hub": e.label}))
            elif e.kind == "Decision":
                calls.append(("decision_detail", {"decision": e.id}))
            elif e.kind in ("Campaign", "Courier"):
                chosen = graph(plan.tenant).ro_query("MATCH (d:Decision)-[:CHOSE]->({id: $x}) RETURN d.id", {"x": e.id}).result_set
                calls += [("decision_detail", {"decision": d}) for d, in chosen]
            elif e.kind == "Region":
                hubs = graph(plan.tenant).ro_query("MATCH (h:Hub)-[:IN]->(:Region {id: $r}) RETURN h.id ORDER BY h.id",
                                                   {"r": e.id}).result_set
                calls += [("hub_status", {"hub": "Hub " + h.split("-")[1].upper()}) for h, in hubs[:4]]
            elif e.kind in ("Product", "Batch"):
                calls.append(("product_status", {"item": e.id if e.kind == "Batch" else e.label,
                                                 "days": max(plan.window["days"], 30)}))
        if "personal_bulk" in p.intents:
            out.append([])  # never walked: Sinew holds no names, emails or phones to list
            continue
        if "verdict" in p.intents:
            calls.append(("prelaunch_check", {}))
        if {"verdict", "detail"} & set(p.intents):  # what the company's own documents say about it
            for e in p.entities:
                if e.kind in ("Campaign", "Decision", "Hub", "Courier"):
                    calls.append(("search_docs", {"text": e.label if e.kind != "Decision" else e.label.split("(")[0]}))
        if {"what_to_do", "detail", "verdict"} & set(p.intents):  # what rests on the thing, not just how it is
            for e in p.entities:
                if e.kind == "Hub":
                    calls += [("trace_decisions", {"hub_id": e.id}), ("prelaunch_check", {})]
                elif e.kind == "Decision":
                    calls.append(("decision_impact", {"decision_id": e.id}))
            if "detail" in p.intents and not p.entities:
                calls += [("company_pulse", {"days": plan.window["days"]}), ("cluster_incidents", {})]
        if "capacity" in p.intents and not any(e.kind == "Hub" for e in p.entities):  # every hub, to compare them
            hubs = graph(plan.tenant).ro_query("MATCH (h:Hub) RETURN h.id ORDER BY h.id").result_set
            calls += [("hub_status", {"hub": "Hub " + h.split("-", 1)[1].upper()}) for h, in hubs]
        if "tickets" in p.intents and not any(e.kind == "Ticket" for e in p.entities):
            calls.append(("ticket_summary", {}))
        if "contact" in p.intents:
            calls += [("customer_trace", {"customer": "#" + e.id[2:] if e.kind == "Order" else e.id})
                      for e in p.entities if e.kind in ("Order", "Ticket")]
        if "attention" in p.intents:
            calls += [("company_pulse", {"days": plan.window["days"]}), ("cluster_incidents", {}), ("prelaunch_check", {})]
        if "rank" in p.intents and "capacity" not in p.intents:
            t = p.text.lower()
            calls.append(("product_ranking", {"days": max(plan.window["days"], 30)}) if re.search(r"product|item|batch", t)
                         else ("company_pulse", {"days": plan.window["days"]}))
        if "why" in p.intents or ("what_to_do" in p.intents and not p.entities):
            calls += [("cluster_incidents", {}), ("prelaunch_check", {})]
        if "what_to_do" in p.intents:
            calls.append(("prelaunch_check", {}))
        other_specific = (SPECIFIC - {"pulse", "tickets"}) & set(p.intents)
        if "pulse" in p.intents or ("count" in p.intents and not p.entities and not other_specific):
            calls.append(("company_pulse", {"days": plan.window["days"]}))
        if ("cost" in p.intents and not any(e.kind == "Order" for e in p.entities)) or "policy" in p.intents:
            calls.append(("search_docs", {"text": p.text}))
        if "cost" in p.intents and not p.entities and re.search(r"revenue|sales|income|turnover|earn|spend this|money in",
                                                                 p.text.lower()):
            calls.append(("company_pulse", {"days": plan.window["days"]}))
        if not calls and not plan.missing:
            calls.append(("search_docs", {"text": p.text}))  # nothing named: maybe a document knows
        seen, unique = set(), []
        for c in calls:
            key = (c[0], json.dumps(c[1], sort_keys=True))
            if key not in seen:
                seen.add(key)
                unique.append(c)
        out.append(unique)
    return out


# ------------------------------------------------------------------ 3. traverse

def follow_up(name: str, result: dict) -> list[tuple[str, dict]]:
    """Steps that depend on an earlier result: a complaint cluster leads to its root hub's decisions, and a
    decision whose assumption no longer holds leads to what rests on it."""
    if result.get("outcome") != "answered_path":
        return []
    if name == "cluster_incidents":
        root = (result["data"].get("clusters") or [{}])[0].get("root_hub")
        return [("trace_decisions", {"hub_id": root})] if root else []
    if name == "trace_decisions":
        broken = [d["decision"] for d in result["data"]["decisions"] if any(a["status"] == "broken" for a in d["assumptions"])]
        linked = [d["decision"] for d in result["data"]["decisions"]
                  if any(a["status"] == "broken" and a.get("linked") for a in d["assumptions"])]
        first = (linked or broken)[:1]
        return [("decision_impact", {"decision_id": first[0]})] if first else []
    return []


async def traverse(plan: Plan, per_part: list[list[tuple[str, dict]]]) -> list[list[dict]]:
    """Run each part's walks as the person asking; add earlier findings (memory) about the things named."""
    done: dict[str, dict] = {}
    results: list[list[dict]] = []
    async with Client(build_server(plan.tenant, plan.user, read_only=True)) as c:
        async def call(name, args):
            key = name + json.dumps(args, sort_keys=True)
            if key not in done:
                t0 = time.perf_counter()
                out = await c.call_tool(name, args)
                try:
                    res = json.loads(out.content[0].text)
                except Exception:
                    res = {"tool": name, "outcome": "error", "reason": out.content[0].text[:200]}
                res["_call"] = {"tool": name, "args": args, "ms": round((time.perf_counter() - t0) * 1000, 1)}
                done[key] = res
            return done[key]

        for calls, part in zip(per_part, plan.parts):
            got, todo = [], list(calls)
            while todo:
                name, args = todo.pop(0)
                res = await call(name, args)
                got.append(res)
                todo += follow_up(name, res)
            for e in part.entities:
                mem = await call("recall", {"about": e.id})
                if mem.get("outcome") == "answered_memory":
                    got.append(mem)
            results.append(got)
    return results


# ------------------------------------------------------------------ 4. reconcile

def _lean(tool: str, d, tenant: str = ""):
    """What an answer needs from a walk: counts, totals and the top few, never long id lists."""
    if not isinstance(d, dict):
        return d
    if tool == "cluster_incidents":
        return {"days": d.get("days"), "clusters": [{k: c[k] for k in ("tickets", "issue", "root_hub", "late_parcels_at_root")}
                                                    | {"shared": c.get("shared", [])[:4]} for c in d.get("clusters", [])[:2]]}
    if tool == "decision_impact":
        waiting = d.get("customers_at_risk", [])
        return {"decision": d.get("decision"), "hubs": d.get("hubs"), "parcels_in_transit": d.get("parcels_in_transit"),
                "customers_waiting": len(waiting), "their_order_value": round(sum(c["order_value"] for c in waiting), 2),
                "gold_customers_waiting": sum(c["tier"] == "gold" for c in waiting),
                "past_delivery_date": sum(bool(c.get("past_promise")) for c in waiting),
                "biggest_waiting": [{k: c[k] for k in ("tier", "order_value", "late_hours")} for c in waiting[:3]],
                "commitments_at_risk": len(d.get("promises_at_risk", [])),
                "decisions_relying_on_it": [x["title"] for x in d.get("dependent_decisions", [])]}
    if tool == "trace_decisions":
        return {"hub": d.get("hub"), "decisions": [
            {"decision": x["decision"], "title": x["title"], "owner": guard.staff_name(tenant, x.get("owner")) if tenant else x.get("owner"), "assumptions": [
                {k: a.get(k) for k in ("statement", "metric", "op", "threshold", "status", "value", "linked", "basis")}
                for a in x["assumptions"]]} for x in d.get("decisions", [])]}
    if tool == "customer_trace":
        t = d.get("timeline", [])
        last_scan = {}
        for i in t:
            if i["kind"] == "scan":
                last_scan[i["id"]] = i
        keep = [i for i in t if i["kind"] != "scan"] + list(last_scan.values())  # latest scan per parcel only
        return {k: v for k, v in d.items() if k not in ("timeline", "profiles")} | {
            "timeline": sorted(keep, key=lambda i: i.get("at") or 0)}
    return d


def _slim(result: dict, tenant: str = "") -> dict:
    tool = result.get("tool")
    out = {k: v for k, v in result.items() if k not in ("paths", "_call", "ms") and v not in ("", [], None)}
    if "data" in out:
        out["data"] = _lean(tool, out["data"], tenant)
    return out


LIMIT = 14000  # characters of fact sheet sent to the model


def for_model(sheet: dict) -> str:
    """The fact sheet as sent to the model. Never cut mid-way: if it is too big, context facts are dropped first,
    then the longest lists are shortened, and the sheet says what was left out. Answers, gaps and next steps stay."""
    text = json.dumps(sheet, default=str)
    if len(text) <= LIMIT:
        return text
    s = json.loads(text)
    left_out = []
    for p in s["parts"]:  # 1. drop facts from walks that only gave context
        keep = [f for f in p["facts"] if f.get("answers", True)]
        if len(keep) < len(p["facts"]):
            left_out.append(f"{len(p['facts']) - len(keep)} context results for \"{p['ask']}\"")
            p["facts"] = keep
    text = json.dumps(s, default=str)
    while len(text) > LIMIT:  # 2. shorten the longest list, keeping its first items
        longest = None
        def walk(o):
            nonlocal longest
            if isinstance(o, list) and len(o) > 2 and (longest is None or len(json.dumps(o)) > len(json.dumps(longest))):
                longest = o
            for v in (o.values() if isinstance(o, dict) else o if isinstance(o, list) else []):
                walk(v)
        walk(s["parts"])
        if longest is None:
            break
        n = len(longest)
        del longest[max(2, n // 2):]
        left_out.append(f"a list shortened from {n} to {len(longest)} items")
        text = json.dumps(s, default=str)
    s["left_out"] = left_out
    return json.dumps(s, default=str)


def _scope(result: dict, plan: Plan) -> str:
    tool = result.get("tool")
    d = result.get("data") or {}
    if tool == "hub_status":
        return d.get("hub", "a hub")
    if tool == "order_detail":
        return f"order {d.get('order')}"
    if tool == "decision_detail":
        return f"decision \"{d.get('decision')}\""
    if tool == "company_pulse":
        return f"whole company, {plan.window['label']}"
    return tool or ""


ANSWERED_BY = {  # which walks can answer an intent; None = any walk about the named thing
    "why": {"cluster_incidents", "trace_decisions", "decision_impact"},
    "what_to_do": {"prelaunch_check", "trace_decisions", "cluster_incidents"},
    "pulse": {"company_pulse"}, "cost": {"search_docs", "company_pulse"}, "policy": {"search_docs", "decision_detail"},
    "count": None, "status": None, "unknown": None,
    "attention": {"company_pulse", "cluster_incidents", "trace_decisions", "prelaunch_check"}, "detail": None,
    "verdict": {"prelaunch_check", "decision_detail", "hub_status", "trace_decisions"},
    "tickets": {"ticket_summary", "company_pulse"}, "capacity": {"hub_status"},
    "rank": {"company_pulse", "product_ranking", "choke_points"},
    "contact": {"customer_trace"}, "personal_bulk": set(),
}
SPECIFIC = {"why", "what_to_do", "pulse", "cost", "policy", "attention", "rank", "contact", "personal_bulk", "verdict", "tickets",
            "capacity"}
MONEY = re.compile(r"\$\s?\d")


def _answers(part: Part, r: dict) -> bool:
    """Does this result answer what the part asks (not just mention the thing it names)?"""
    if r.get("outcome") not in ("answered_path", "answered_memory"):
        return False
    primary = [i for i in part.intents if i in SPECIFIC] or part.intents
    for intent in primary:
        if intent == "cost" and r.get("tool") == "order_detail":
            return True  # what a named order cost is its total
        tools = ANSWERED_BY.get(intent)
        if tools is not None and r.get("tool") not in tools:
            continue
        if intent == "cost":  # answered only by an actual figure of the kind asked: revenue, or costs and spend
            d = r.get("data") or {}
            if r.get("tool") == "company_pulse":
                fin = d.get("finance") or {}
                wants_revenue = re.search(r"revenue|sales|income|turnover|earn", part.text.lower())
                body = json.dumps({k: fin.get(k) for k in (("revenue_this_week", "revenue_last_week") if wants_revenue
                                                           else ("delivery_cost", "campaign_spend"))})
            else:
                body = json.dumps(d)
            if not MONEY.search(body or ""):
                continue
        return True
    return False


def reconcile(plan: Plan, results: list[list[dict]]) -> dict:
    """One fact sheet: each part's facts with their scope, what's missing and why, and next steps that follow."""
    parts, recs, hidden = [], [], []
    for part, got in zip(plan.parts, results):
        answering = [r for r in got if _answers(part, r)]
        context = [r for r in got if r not in answering and r.get("outcome") in ("answered_path", "answered_memory")
                   and not ({"cost", "policy"} & set(part.intents))]  # a status is not an answer to a cost question
        blocked = [r for r in got if r.get("outcome") == "not_permitted" or r.get("hidden")]
        for r in got:
            for h in r.get("hidden") or []:
                if h not in hidden:
                    hidden.append(h)
        if "personal_bulk" in part.intents:
            status, why = "no_access", ("Sinew doesn't hold customers' names, emails or phone numbers, so it can't list "
                                        "them; contact details are fetched one customer at a time, for people allowed")
        elif answering:
            status, why = "answered", ""
        elif plan.missing and not answering:
            status, why = "no_data", "there is no " + " or ".join(plan.missing)
        elif blocked:
            status, why = "no_access", next((r.get("reason") for r in blocked if r.get("reason")), "")
        else:
            status, why = "no_data", next((r.get("reason") for r in got if r.get("reason")), "")
        keep = answering + (context if answering or not blocked else [])
        answered = [r for r in got if r in keep]  # in the order walked: what was named first, then what rests on it
        facts = [{"scope": _scope(r, plan), "from": r.get("tool"), "named": [e.id for e in part.entities],
                  "asked": part.text, "intents": part.intents,
                  "answers": r in answering, **_slim(r, plan.tenant)} for r in answered]
        parts.append({"ask": part.text, "intents": part.intents, "named": [e.label for e in part.entities],
                      "status": status, "why_missing": why, "facts": facts})
        if {"what_to_do", "why", "verdict"} & set(part.intents):
            recs += _recommend(got)
    # Two on-time figures with different scopes are not a conflict; say which is which.
    notes = []
    scopes = {f["scope"] for p in parts for f in p["facts"] if f["from"] in ("hub_status", "company_pulse")}
    if len(scopes) > 1:
        notes.append("On-time figures differ by scope: " + " vs ".join(sorted(scopes)) + "; both are correct for their scope.")
    seen, unique_recs = set(), []
    for r in recs:
        if r not in seen:
            seen.add(r)
            unique_recs.append(r)
    you = {"role": plan.role, "refund_limit": plan.refund_limit} if re.search(r"refund|limit|approve|can i", plan.question.lower()) else None
    return {"question": plan.question, "follows": plan.follow_up_to or None, "asked_by": plan.role, "you": you, "window": plan.window["label"], "parts": parts,
            "what_to_do": unique_recs[:3] if any({"what_to_do", "verdict"} & set(p.intents) for p in plan.parts) else [],
            "hidden": hidden, "notes": notes}


def _recommend(got: list[dict]) -> list[str]:
    """Next steps that follow from the facts, never invented: a reroute the graph found, a decision to review."""
    out = []
    for r in got:
        d = r.get("data") or {}
        if r.get("tool") == "hub_status" and r.get("outcome") == "answered_path" and d.get("busiest_day_parcels", 0) > d.get("capacity_per_day", 1e9):
            out.append(f"{d['hub']} handled up to {d['busiest_day_parcels']} parcels in a day against a capacity of "
                       f"{d['capacity_per_day']}, so it cannot carry sale volume on its own: plan a second route or limit the offer.")
        if r.get("tool") == "prelaunch_check" and r.get("outcome") == "answered_path":
            for w in d.get("warnings", []):
                if w.get("reroute"):
                    hub = w["reroute"]["hub"].split("-", 1)[1].upper()
                    out.append(f"Route the {w['name']} through Hub {hub} instead of {w['hub'].replace('hub-', 'Hub ').upper().replace('HUB', 'Hub')} "
                               f"(about {w['reroute']['hours']:g} h, room for {w['reroute']['capacity']} parcels a day).")
        if r.get("tool") == "trace_decisions" and r.get("outcome") == "answered_path":
            for dec in d.get("decisions", []):
                broken = [a for a in dec["assumptions"] if a["status"] == "broken" and a.get("linked")]
                if broken:
                    out.append(f"Review \"{dec['title']}\" with its owner: it assumed {broken[0]['statement'][0].lower() + broken[0]['statement'][1:]}, "
                               "and that no longer holds.")
                    break
    return out


# ------------------------------------------------------------------ 4b. actions the facts call for

def actions(plan: Plan, results: list[list[dict]]) -> list[dict]:
    """Actions the facts warrant, for the person to confirm (each is permission-checked before it is offered):
    a broken decision behind a complaint cluster -> open an incident and tell the decision's owner;
    a customer's overdue agreed refund -> refund it."""
    flat = [r for got in results for r in got if r.get("outcome") == "answered_path"]
    out = []
    cluster = next(((r["data"].get("clusters") or [None])[0] for r in flat if r.get("tool") == "cluster_incidents"), None)
    decisions = next((r["data"].get("decisions", []) for r in flat if r.get("tool") == "trace_decisions"), [])
    broken = [d for d in decisions if any(a["status"] == "broken" and a.get("linked") for a in d["assumptions"])] or \
             [d for d in decisions if any(a["status"] == "broken" for a in d["assumptions"])]
    if cluster and broken and any({"why", "what_to_do", "attention"} & set(p.intents) for p in plan.parts):
        hub = cluster["root_hub"].replace("hub-", "Hub ").upper().replace("HUB", "Hub")
        issue = cluster["issue"].replace("_", " ")
        out.append({"name": "file_incident", "args": {"title": f"{issue.capitalize()} complaints at {hub}",
                                                      "ticket_ids": cluster["ticket_ids"], "root_hub": cluster["root_hub"]}})
        d = broken[0]
        a = next(x for x in d["assumptions"] if x["status"] == "broken")
        now = f"{round(a['value'] * 100)}%" if a["metric"] == "courier_on_time_rate" else f"{a['value']:.2f}x capacity"
        out.append({"name": "notify_owner", "args": {"decision_id": d["decision"], "message":
                    f"Your decision \"{d['title']}\" assumed: {a['statement']}. This week it is {now}. "
                    f"{cluster['tickets']} {issue} complaints went through {hub}."}})
    for r in flat:
        if r.get("tool") == "open_loops":
            for p in (r["data"].get("broken_promises") or [])[:1]:
                if p.get("promise") == "refund":
                    total = graph(plan.tenant).ro_query("MATCH (o:Order {id: $o}) RETURN o.total", {"o": p["order"]}).result_set
                    if total:
                        out.append({"name": "issue_refund", "args": {"order_id": p["order"], "amount": total[0][0]}})
    return out


# ------------------------------------------------------------------ 5. write (from the fact sheet only)

def _when(at) -> str:
    return time.strftime("%-d %b", time.gmtime(at)) if at else "?"


def _money(x) -> str:
    return x if isinstance(x, str) else f"${x:,.2f}"


def _say_fact(f: dict) -> list[str]:
    d = f.get("data") or {}
    tool = f["from"]
    if tool == "order_detail":
        dl = d["delivery"]
        state = f"delivered on {dl['delivered_on']}" if dl["delivered"] else f"{dl['status']}" + (f", {dl['late_hours']} h late" if dl.get("late_hours") else "")
        lines = [f"Order {d['order']}: {_money(d['total'])}, {state}."]
        if d.get("refunded_total"):
            lines.append(f"Refunded: {_money(d['refunded_total'])}.")
        open_c = [c for c in d.get("commitments", []) if c["overdue"]]
        if open_c:
            lines.append(f"Overdue: a {open_c[0]['kind']} that was due {open_c[0]['due']}.")
        return lines
    if tool == "decision_detail":
        lines = [f"\"{d['decision']}\" (made {d['made']}{', owned by ' + d['owner'] if d.get('owner') else ''})."]
        for a in d.get("assumptions", []):
            lines.append(f"It assumed {a['assumed'][0].lower() + a['assumed'][1:]}: needs {a['needs']}, now {a['now']}"
                         + (" (holds)." if a["holds"] else " (no longer holds)."))
        if d.get("campaign", {}).get("starts_in_days") and "verdict" not in f.get("intents", []):  # the verdict says it
            lines.append(f"{d['campaign']['name']} starts in {d['campaign']['starts_in_days']} days.")
        return lines
    if tool == "hub_status":
        return [f"{d['hub']}: {d['parcels_there_now']} parcels there now for {d['customers_waiting']} customers, "
                f"{d['late_now']} late; on time this week {d['on_time_this_week']}; capacity {d['capacity_per_day']} a day."]
    if tool == "company_pulse" and "cost" in f.get("intents", []):  # a money question gets money lines only
        fin = d.get("finance") or {}
        before = lambda x: f" (before: {x})" if x not in (0, None, "$0.00") else ""
        return ([f"Revenue: {fin['revenue_this_week']}{before(fin['revenue_last_week'])}.",
                 f"Refunds paid: {fin['refunds_paid_this_week']}."] if fin else [])
    if tool == "company_pulse":
        lines = []
        before = lambda x: f" (before: {x})" if x not in (0, None, "$0.00") else ""
        if d.get("support"):
            lines.append(f"Tickets: {d['support']['tickets_this_week']}{before(d['support']['tickets_last_week'])}.")
        if d.get("operations") and d["operations"].get("on_time_rate") is not None:
            lines.append(f"On time: {round(d['operations']['on_time_rate'] * 100)}% of deliveries; "
                         f"{d['operations']['parcels_late_now']} parcels late now.")
            weak = d["operations"].get("weakest_hub")
            if weak:
                lines.append(f"Weakest hub: {weak['hub'].replace('hub-', 'Hub ').upper().replace('HUB', 'Hub')} at "
                             f"{round(weak['on_time_rate'] * 100)}% on time.")
        if d.get("marketing"):
            lines.append(f"Orders: {d['marketing']['orders_this_week']}{before(d['marketing']['orders_last_week'])}.")
        if d.get("finance"):
            lines.append(f"Revenue: {d['finance']['revenue_this_week']}{before(d['finance']['revenue_last_week'])}.")
        return lines
    if tool == "search_docs":  # the passages that share the most words with the question, a named document first
        asked = set(re.findall(r"[a-z0-9]{4,}", f.get("asked", "").lower()))
        def fit(x):
            title = set(re.findall(r"[a-z0-9]{4,}", x["title"].lower()))
            body = set(re.findall(r"[a-z0-9]{4,}", f"{x['heading']} {x['text']}".lower()))
            return (len(asked & title) * 3 + len(asked & body))
        ranked = sorted(f.get("data") or [], key=fit, reverse=True)
        return [f"{x['title']}, \"{x['heading']}\": {x['text']}" for x in ranked[:3]]
    if tool == "ticket_summary":
        lines = [f"{d['open']} open tickets ({d['scope']}): " + ", ".join(f"{x['tickets']} {x['issue']}" for x in d["by_issue"][:4]) + "."]
        if len(d["by_region"]) > 1:
            lines.append("By region: " + ", ".join(f"{x['region']} {x['tickets']}" for x in d["by_region"]) + ".")
        lines.append(f"The longest wait is {d['oldest_waiting_days']:g} days.")
        if d.get("most_urgent"):
            lines.append("Most urgent: " + "; ".join(
                f"{x['customer']} ({x['issue']}, waiting {x['waiting_days']:g} days" + (f"; {' and '.join(x['flags'])}" if x["flags"] else "") + ")"
                for x in d["most_urgent"]) + ".")
        return lines
    if tool == "product_ranking":
        return [f"Most complaints per 100 orders, last {d['days']} days: " + "; ".join(
            f"{x['product']} {x['per_100']} ({x['complaints']} of {x['orders']} orders)" for x in d.get("products", [])[:3]) + "."]
    if tool == "customer_trace":
        kinds = [i["kind"] for i in d.get("timeline", [])]
        contact = d.get("personal") or {}
        lines_c = [f"Contact: {', '.join(str(contact[k]) for k in ('name', 'phone', 'email') if contact.get(k))}."] if contact else []
        tickets = [i for i in d.get("timeline", []) if i["kind"] == "ticket"]
        current = next((i for i in tickets if i["id"] in f.get("named", [])), tickets[-1] if tickets else None)
        n = lambda k, word: f"{kinds.count(k)} {word}{'' if kinds.count(k) == 1 else 's'}"
        lines = lines_c + [f"This customer has {n('order', 'order')}, {n('ticket', 'ticket')} and {n('refund', 'refund')}."]
        if current:
            lines.append(f"Latest ticket ({(current.get('issue') or '').replace('_', ' ')}, {current.get('status')}): "
                         f"\"{current.get('summary')}\"")
        return lines
    if tool == "open_loops":
        lines = []
        for p in d.get("broken_promises", []):
            lines.append(f"Overdue: a {p['promise']} on order #{p['order'][2:]} was due {_when(p['due_at'])}.")
        for s in d.get("late_in_transit", []):
            lines.append(f"Late: order #{s['order'][2:]} is at {s['hub'].replace('hub-', 'Hub ').upper().replace('HUB', 'Hub')}, {s['late_hours']} h late.")
        for p in d.get("open_promises", []):
            lines.append(f"Still due: a {p['promise']} on order #{p['order'][2:]} by {_when(p['due_at'])}.")
        others = len(d.get("open_tickets", [])) - 1
        if others > 0:
            lines.append(f"{others} other open tickets from this customer.")
        return lines
    if tool == "related_issues" and d.get("shared"):
        s = d["shared"][0]
        top = [x for x in d["shared"] if x["other_tickets"] == s["other_tickets"]]
        name = lambda i: i.replace("hub-", "Hub ").replace("courier-", "Courier ").upper().replace("HUB", "Hub").replace("COURIER", "Courier")
        return [f"{s['other_tickets']} other tickets in the last {d.get('days')} days went through the same places: "
                f"{', '.join(name(x['id']) for x in top)}."]
    if tool == "trace_decisions":
        lines, said_overlap = [], False
        for dec in d.get("decisions", []):
            for a in dec["assumptions"]:
                if a["status"] == "broken":
                    now_v = f"{round(a['value'] * 100)}%" if a["metric"] == "courier_on_time_rate" else f"{a['value']:.2f}x capacity"
                    need = f"{round(a['threshold'] * 100)}%" if a["metric"] == "courier_on_time_rate" else f"{a['threshold']:.2f}x"
                    lines.append(f"\"{dec['title']}\" assumed {a['statement'][0].lower() + a['statement'][1:]}; it is now {now_v} (needed {need}).")
                    if a.get("linked") and not said_overlap:
                        said_overlap = True
                        lines.append("At the same time, " + a["basis"].replace("campaign fest40", "the FEST40 campaign")
                                     .replace("hub-w2", "Hub W2") + ". That is an overlap in the data, not proof of cause.")
                    break
        return lines[:4]
    if tool == "decision_impact":
        n = d.get("customers_waiting", 0)
        hubs = ", ".join(h.replace("hub-", "Hub ").upper().replace("HUB", "Hub") for h in d.get("hubs") or [])
        line = f"{n} customers are still waiting on {d.get('parcels_in_transit')} parcels" + (f" at {hubs}" if hubs else "")
        if n:
            line += (f" (${d['their_order_value']:,.2f} of orders; {d['gold_customers_waiting']} gold; "
                     f"{d['past_delivery_date']} already past their delivery date)")
        big = d.get("biggest_waiting") or []
        if big and "detail" in f.get("intents", []):
            line += ". Largest waiting orders: " + ", ".join(
                f"${c['order_value']:,.2f} ({c['tier']}{', ' + str(int(c['late_hours'])) + ' h late' if c.get('late_hours') else ''})" for c in big)
        rel = d.get("decisions_relying_on_it", [])
        return [line + (f"; {len(rel)} other decisions rely on this one: " + "; ".join(f'"{t}"' for t in rel) if rel else "") + "."]
    if tool == "prelaunch_check":
        return [f"{w['name']} starts in {w['starts_in_days']:g} days and its parcels go through "
                f"{w['hub'].replace('hub-', 'Hub ').upper().replace('HUB', 'Hub')}, which is already struggling."
                for w in d.get("warnings", [])]
    if tool == "product_status":
        base = f" Across all products it is {d['baseline_complaints_per_100_orders'].split(' per')[0]} per 100." if d.get("baseline_complaints_per_100_orders") else ""
        return [f"{d['item']}, last {d['days']} days: {d['orders']} orders, {d['complaints']} complaints "
                f"({d['complaints_per_100_orders']}; {d['quality_complaints']} about the product itself), "
                f"{d['returns']} returns.{base}"]
    if tool == "cluster_incidents" and d.get("clusters"):
        c = d["clusters"][0]
        return [f"{c['tickets']} {c['issue'].replace('_', ' ')} complaints went through {c['root_hub'].replace('hub-', 'Hub ').upper().replace('HUB', 'Hub')}."]
    if tool == "recall":
        return [f"Noted earlier: {x['text']}" for x in (f.get("data") or [])[:1]]
    return []


def _verdict(sheet: dict) -> str | None:
    """A yes/no for "is it safe to launch?" taken from the facts: a scheduled campaign whose hub's assumptions
    are already failing, or a decision whose own assumptions no longer hold."""
    facts = [f for p in sheet["parts"] if "verdict" in p["intents"] for f in p["facts"]]
    if not facts:
        return None
    named = {n for f in facts for n in f.get("named", [])}
    warns = [w for f in facts if f["from"] == "prelaunch_check" for w in (f.get("data") or {}).get("warnings", [])]
    mine = [w for w in warns if w["campaign"] in named] or ([w for w in warns[:1]] if not any(n in named for n in ("fest40",)) else [])
    if mine:
        w = mine[0]
        hub = w["hub"].replace("hub-", "Hub ").upper().replace("HUB", "Hub")
        why = []
        for a in w["broken_assumptions"]:
            part = (f"on-time delivery is already {round(a['value'] * 100)}%" if a["metric"] == "courier_on_time_rate"
                    else f"it is already carrying {a['value']:.2f}x its daily capacity")
            if part not in why:
                why.append(part)
        return (f"No, not as things stand. The {w['name']} starts in {w['starts_in_days']:g} days and its parcels go through "
                f"{hub}, where " + " and ".join(why) + ".")
    for f in facts:
        if f["from"] == "decision_detail":
            bad = [a for a in f["data"]["assumptions"] if not a["holds"]]
            if bad:
                return f"Not as things stand: {len(bad)} of the assumptions behind this decision no longer hold."
            return "Yes: nothing in the data says it won't work, and the assumptions behind it still hold."
    return None


def write(sheet: dict) -> str:
    """A plain, correct answer built from the fact sheet alone (used when the AI is unavailable or its wording
    fails the check)."""
    lines = []
    verdict = _verdict(sheet)
    if verdict:
        lines.append(verdict)
    if not sheet["parts"]:
        return "Ask me something about your company: an order, a hub, a decision, a policy, or how things are going."
    for p in sheet["parts"]:
        hubs = [f["data"] for f in p["facts"] if f["from"] == "hub_status" and f.get("data", {}).get("load_vs_capacity") is not None]
        if "capacity" in p["intents"] and hubs:
            hubs.sort(key=lambda h: -h["load_vs_capacity"])
            said = re.search(r"(\d+(?:\.\d+)?)\s*%|(\d\.\d+)\s*x\b", sheet["question"].lower())
            if said:  # the figure the person quotes ("157%") leads: say which hub it is
                target = float(said.group(1) or 0) / 100 if said.group(1) else float(said.group(2))
                hubs.sort(key=lambda h: abs(h["load_vs_capacity"] - target) > 0.011)
            over = [h for h in hubs if h["load_vs_capacity"] > 1]
            under = [h for h in hubs if h["load_vs_capacity"] <= 1]
            if over:
                top = over[0]
                lines.append(f"{top['hub']} is at {top['load_vs_capacity']:.2f}x its capacity: its busiest day this week had "
                             f"{top['busiest_day_parcels']} parcels against {top['capacity_per_day']} a day.")
                if len(over) > 1:
                    lines.append("Also over capacity: " + "; ".join(f"{h['hub']} {h['load_vs_capacity']:.2f}x" for h in over[1:]) + ".")
            else:
                lines.append("No hub went over its daily capacity this week.")
            if under:
                lines.append("Within capacity (busiest day against daily capacity): " + "; ".join(
                    f"{h['hub']} {h['busiest_day_parcels']} of {h['capacity_per_day']} ({h['load_vs_capacity']:.2f}x)" for h in under) + ".")
            p["facts"] = [f for f in p["facts"] if f["from"] != "hub_status"]
            if not p["facts"]:
                p["status"] = "handled"
    if sheet.get("you") and sheet["you"].get("refund_limit") is not None and any("policy" in p["intents"] for p in sheet["parts"]):
        lim = sheet["you"]["refund_limit"]
        asked = re.search(r"\$\s?(\d+(?:\.\d+)?)", sheet["question"])
        if asked and lim:
            amount = float(asked.group(1))
            lines.append(f"Yes: your refund limit is {_money(lim)}, so you can refund {_money(amount)} yourself." if amount <= lim
                         else f"No: your refund limit is {_money(lim)}, so {_money(amount)} needs approval from someone with a "
                              "higher limit (Sinew sends it to them when you issue it).")
        else:
            lines.append(f"Your own refund limit is {_money(lim)}." if lim else "Your role can't issue refunds itself.")
    for p in sheet["parts"]:
        if p["status"] == "no_access" and "personal_bulk" in p["intents"]:
            lines.append(p["why_missing"][0].upper() + p["why_missing"][1:] + ".")
        elif p["status"] == "no_access":
            lines.append("That's outside your access.")
        elif p["status"] == "handled":
            continue  # said above
        elif p["status"] == "no_data" and sheet.get("you") and "policy" in p["intents"]:
            continue  # the person's own limit (above) already answers it
        elif p["status"] == "no_data":
            known = p["why_missing"] if p["why_missing"].startswith("there is no") else ""
            lines.append(f"Sinew has no information about that{': ' + known if known else ''}.")
        elif "rank" in p["intents"] and any(f["from"] == "company_pulse" for f in p["facts"]):
            weak = next((f["data"]["operations"].get("weakest_hub") for f in p["facts"]
                         if f["from"] == "company_pulse" and (f.get("data") or {}).get("operations")), None)
            lines.append(f"The weakest hub {sheet['window']} is {weak['hub'].replace('hub-', 'Hub ').upper().replace('HUB', 'Hub')}, "
                         f"at {round(weak['on_time_rate'] * 100)}% on time." if weak else "Sinew has no information about that.")
        else:
            for f in p["facts"]:
                lines += _say_fact(f)
    if sheet["what_to_do"]:
        lines.append("What to do:")
        lines += [f"- {r}" for r in sheet["what_to_do"]]
    refused = any(p["status"] == "no_access" for p in sheet["parts"])
    for h in sheet["hidden"][:2]:
        if h.get("kind") == "passage" and refused:
            continue  # already said: "That's outside your access."
        if h.get("kind") == "passage":
            lines.append("Some matching documents are outside your access.")
        elif h.get("kind") == "ticket":
            lines.append(f"{h['count']} of their tickets {'is' if h['count'] == 1 else 'are'} in other teams' queues and not shown.")
        elif h.get("kind") == "area" and not refused and any({"pulse", "attention"} & set(p["intents"]) for p in sheet["parts"]):
            lines.append(h["reason"][0].upper() + h["reason"][1:] + ".")  # only a summary needs to say what it left out
        elif h.get("kind") == "payment":
            lines.append(h["reason"][0].upper() + h["reason"][1:] + ".")
    lines = [re.sub(r"\[(NAME|PHONE|EMAIL|CARD|HANDLE)\]", lambda m: f"({m.group(1).lower()} removed)", x) for x in lines]
    seen, out = set(), []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out) or "Sinew couldn't find anything about that."


async def analyse(tenant: str, user_id: str, question: str, history=()) -> tuple[Plan, list[list[dict]], dict]:
    plan = understand(tenant, user_id, question, history)
    results = await traverse(plan, walks(plan))
    sheet = reconcile(plan, results)
    sheet["actions"] = actions(plan, results)
    return plan, results, sheet
