"""The sentence check (RESOURCES.md R4): the model's answer may only name things and numbers the tools returned.

- Every id-like name in the answer (o-4412, hub-w2, dec-courier-y, fest40, ...) must appear in a tool result.
- Every number must appear in a tool result, or be a tool fraction written as a percentage (0.7117 -> 71%),
  or appear in the question itself.
- An answer that claims impact when every tool came back empty is rejected.
If the check fails, the caller shows a sentence built from the rows instead.
"""

import json
import re
import time

ID = re.compile(r"\b(?:o|t|cu|pf|hub|dec|as|sh|rf|pr|inc|u|fd|note|courier|b|sup|wh|q|team)-[a-z0-9][a-z0-9-]*\b"
                r"|\b(?:fest|winter)\d+\b", re.I)
NUMBER = re.compile(r"(?<![\w.#,-])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(%?)")  # 17,949.49 is one number  # "#4412" is an order, checked as a name below
# Names as people write them, checked as the ids they stand for: #4412 -> o-4412, Hub W2 -> hub-w2, Courier Y -> courier-y.
PLAIN = [(re.compile(r"#(\d+)\b"), "o-{}"), (re.compile(r"\bHub ([A-Z]\d+)\b"), "hub-{}"),
         (re.compile(r"\bCourier ([A-Z])\b"), "courier-{}")]


def _numbers_in(blob: str) -> set[float]:
    return {float(n.replace(",", "")) for n, _ in NUMBER.findall(blob)}


def check(answer: str, tool_results: list[dict], question: str = "", extra: str = "") -> tuple[bool, str]:
    """`extra` is more text the model was given (the fact sheet), whose names and numbers are allowed too."""
    blob = json.dumps(tool_results, default=str).lower() + " " + extra.lower()
    for name in {m.group(0).lower().rstrip("-.") for m in ID.finditer(answer)}:
        if name not in blob:
            return False, f"names {name!r}, which no tool returned"
    for pattern, template in PLAIN:
        for m in pattern.finditer(answer):
            if template.format(m.group(1)).lower() not in blob and m.group(0).lower() not in blob:  # code or words
                return False, f"names {m.group(0)!r}, which no tool returned"
    known = _numbers_in(blob) | _numbers_in(question)
    for raw, pct in NUMBER.findall(answer):
        n = float(raw.replace(",", ""))
        if n in known:
            continue
        if pct and any(abs(n / 100 - k) < 0.006 for k in known):  # 0.7658 -> 77%, a 1.5714 load -> 157%
            continue
        if pct and any(abs(n - k) < 1.0 for k in known if k > 1):  # a computed change of 24.8 written as 24% or 25%
            continue
        if any(abs(n - round(k)) < 1e-9 or abs(n - round(k, 1)) < 1e-9 or abs(n - round(k, 2)) < 1e-9
               or abs(n - int(k)) < 1e-9 for k in known):
            continue  # a rounded tool value
        return False, f"states the number {raw}{pct}, which no tool returned"
    if any(r.get("tool") in ("trace_decisions", "decision_impact", "prelaunch_check") for r in tool_results):
        claim = re.search(r"\b(because|caused|causing|due to|root cause|driven by|led to|leads to|resulted in|result of|overload(?:ed|ing)? by|will (?:fail|break|cause))\b",
                          answer, re.I)
        if claim:
            return False, f"says {claim.group(0)!r}: decision links are overlaps in the data, not causes"
    if tool_results and all(r.get("outcome") in ("not_in_graph", "unknown_entity", "not_permitted")
                            for r in tool_results):
        if re.search(r"\b(affect|impact|caused|broke|late|at risk)\w*", answer, re.I):
            return False, "claims impact although every tool came back empty"
    return True, ""


def _place(x: str | None) -> str:
    """hub-w2 -> Hub W2, courier-y -> Courier Y, fest40 -> FEST40, o-4412 -> #4412."""
    if not x:
        return "?"
    if x.startswith("o-"):
        return "#" + x[2:]
    head, _, rest = x.partition("-")
    return f"{head.capitalize()} {rest.upper()}" if rest else x.upper()


def _plain(text: str) -> str:
    """Ids inside engine sentences: "campaign fest40 ... hub-w2" -> "the FEST40 campaign ... Hub W2"."""
    text = re.sub(r"\bcampaign ([a-z]+\d+)\b", lambda m: f"the {m.group(1).upper()} campaign", text)  # fest40, not "running"
    text = re.sub(r"\b1[6-9]\d{8}\b", lambda m: time.strftime("%-d %b, %H:%M", time.gmtime(int(m.group(0)))), text)  # timestamps
    text = re.sub(r"\bo-(\d+)\b", r"#\1", text)
    text = re.sub(r"\s*\(?\b(?:pr|cu|pf|sh|rf|rt|as|pay)-[a-z0-9-]+\)?", "", text)  # internal codes
    text = re.sub(r"\s*\(?\b(?:under |in )?(?:ticket )?t-\d+\)?", "", text)  # ticket codes: "this ticket" is enough
    text = re.sub(r"\bpromised\b", "agreed", text)
    text = re.sub(r"\bpromise(s?)\b", r"commitment\1", text)
    return re.sub(r"\b(?:hub|courier)-[a-z0-9]+\b", lambda m: _place(m.group(0)), text)


plain = _plain  # used by the loop on answers that passed the check: same facts, people's names for them


def _pct(v) -> str:
    return f"{round(v * 100)}%" if isinstance(v, (int, float)) and v <= 1 else str(v)


def coverage(draft: str, answer: str) -> tuple[float, list[str]]:
    """How much of the draft's numbers survive in the rewrite. A ratio and a percentage count as the same number
    (1.57 and 157%), and so do a figure and its rounding. (fraction kept, the numbers that were left out)"""
    def nums(text: str) -> set[float]:
        return {float(n.replace(",", "")) for n, _ in NUMBER.findall(text)}
    want, have = nums(draft), nums(answer)
    want = {w for w in want if w not in (0.0, 1.0)}  # a bare 0 or 1 says nothing
    def kept(w: float) -> bool:
        return any(abs(w - h) < 0.006 or abs(w * 100 - h) < 0.6 or abs(w - h * 100) < 0.6 or abs(w - round(h)) < 0.006
                   or abs(round(w) - h) < 0.006 for h in have)
    missing = sorted(w for w in want if not kept(w))
    return (1 - len(missing) / len(want) if want else 1.0), [f"{m:g}" for m in missing]


def fallback(tool_results: list[dict]) -> str:
    """Plain sentences built only from the rows, for when the model's own answer fails the check."""
    out = []
    for r in tool_results:
        tool, outcome, d = r.get("tool"), r.get("outcome"), r.get("data") or {}
        if outcome in ("not_in_graph", "unknown_entity", "not_permitted", "needs_approval"):
            out.append(f"{r.get('reason', '').capitalize()}.")
        elif tool == "company_pulse":
            s = d.get("support") or {}
            o = d.get("operations") or {}
            m = d.get("marketing") or {}
            f = d.get("finance") or {}
            if m:
                out.append(f"Orders this week: {m['orders_this_week']} (last week {m['orders_last_week']}).")
            if f:
                out.append(f"Revenue this week: {f['revenue_this_week']} (last week {f['revenue_last_week']}).")
            if s:
                out.append(f"Tickets this week: {s['tickets_this_week']} (last week {s['tickets_last_week']}).")
            if o and o.get("on_time_rate") is not None:
                out.append(f"On-time delivery: {_pct(o['on_time_rate'])}; {o['parcels_late_now']} parcels late now.")
            for h in r.get("hidden", []):
                out.append(h["reason"][0].upper() + h["reason"][1:] + ".")
        elif tool == "search_docs":
            for doc in d[:2]:
                out.append(f"{doc['title']}, \"{doc['heading']}\": {doc['text']}")
        elif tool == "customer_trace":
            kinds = [i["kind"] for i in d.get("timeline", [])]
            out.append(f"This customer has {kinds.count('order')} orders, {kinds.count('ticket')} tickets and "
                       f"{kinds.count('refund')} refunds.")
        elif tool == "open_loops":
            parts = [(len(d.get("open_tickets", [])), "open ticket"), (len(d.get("broken_promises", [])), "overdue commitment"),
                     (len(d.get("open_promises", [])), "commitment still due"), (len(d.get("late_in_transit", [])), "late parcel")]
            out.append("Still open: " + ", ".join(f"{n} {w}{'s' if n != 1 else ''}" for n, w in parts if n) + ".")
        elif tool == "related_issues" and d.get("shared"):
            s = d["shared"][0]
            out.append(f"{s['other_tickets']} other tickets in the last {d.get('days')} days went through "
                       f"{_place(s['id'])}.")
        elif tool == "cluster_incidents" and d.get("clusters"):
            c = d["clusters"][0]
            out.append(f"{c['tickets']} {c['issue'].replace('_', ' ')} complaints went through {_place(c['root_hub'])}.")
        elif tool == "trace_decisions":
            said_overlap = False
            for dec in d.get("decisions", []):
                for a in dec["assumptions"]:
                    if a.get("status") == "broken":
                        need = {">=": "at least", "<=": "at most"}.get(a["op"], a["op"])
                        link = ""
                        if a.get("linked") and not said_overlap:
                            link, said_overlap = f" At the same time, {_plain(a['basis'])}.", True
                        out.append(f"\"{dec['title']}\" assumed {a['statement'][0].lower() + a['statement'][1:]}; "
                                   f"this week it is {_pct(a['value'])} (needed {need} {_pct(a['threshold'])}).{link}")
        elif tool == "decision_impact":
            out.append(f"{len(d.get('customers_at_risk', []))} customers are still waiting on "
                       f"{d.get('parcels_in_transit')} parcels, and {len(d.get('dependent_decisions', []))} other "
                       f"decisions rely on this one.")
        elif tool == "prelaunch_check":
            for w in d.get("warnings", []):
                reroute = f" Option: route through {_place(w['reroute']['hub'])}." if w.get("reroute") else ""
                out.append(f"{w.get('name', _place(w['campaign']))} starts in {w['starts_in_days']:g} days through "
                           f"{_place(w['hub'])}, which is already struggling.{reroute}")
    found = [o for o in dict.fromkeys(out) if o and not o.endswith(": .")]
    if not found or all(r.get("outcome") in ("not_in_graph", "unknown_entity") for r in tool_results):
        return "Sinew couldn't find anything about that in the company's data or documents."
    return "Here is what Sinew found:\n" + "\n".join(f"- {o}" for o in found[:4])
