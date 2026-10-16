"""The sentence check (RESOURCES.md R4): the model's answer may only name things and numbers the tools returned.

- Every id-like name in the answer (o-4412, hub-w2, dec-courier-y, fest40, ...) must appear in a tool result.
- Every number must appear in a tool result, or be a tool fraction written as a percentage (0.7117 -> 71%),
  or appear in the question itself.
- An answer that claims impact when every tool came back empty is rejected.
If the check fails, the caller shows a sentence built from the rows instead.
"""

import json
import re

ID = re.compile(r"\b(?:o|t|cu|pf|hub|dec|as|sh|rf|pr|inc|u|fd|note|courier|b|sup|wh|q|team)-[a-z0-9][a-z0-9-]*\b"
                r"|\b(?:fest|winter)\d+\b", re.I)
NUMBER = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)(%?)")


def _numbers_in(blob: str) -> set[float]:
    return {float(n) for n, _ in NUMBER.findall(blob)}


def check(answer: str, tool_results: list[dict], question: str = "") -> tuple[bool, str]:
    blob = json.dumps(tool_results, default=str).lower()
    for name in {m.group(0).lower().rstrip("-.") for m in ID.finditer(answer)}:
        if name not in blob:
            return False, f"names {name!r}, which no tool returned"
    known = _numbers_in(blob) | _numbers_in(question)
    for raw, pct in NUMBER.findall(answer):
        n = float(raw)
        if n in known:
            continue
        if pct and any(abs(n / 100 - k) < 0.006 for k in known if k <= 1):
            continue
        if any(abs(n - round(k)) < 1e-9 or abs(n - round(k, 1)) < 1e-9 or abs(n - round(k, 2)) < 1e-9 for k in known):
            continue  # a rounded tool value
        return False, f"states the number {raw}{pct}, which no tool returned"
    if any(r.get("tool") in ("trace_decisions", "decision_impact", "prelaunch_check") for r in tool_results):
        claim = re.search(r"\b(because|caused|causing|due to|overload(?:ed|ing)? by|will (?:fail|break|cause))\b",
                          answer, re.I)
        if claim:
            return False, f"says {claim.group(0)!r}: decision links are overlaps in the data, not causes"
    if tool_results and all(r.get("outcome") in ("not_in_graph", "unknown_entity", "not_permitted")
                            for r in tool_results):
        if re.search(r"\b(affect|impact|caused|broke|late|at risk)\w*", answer, re.I):
            return False, "claims impact although every tool came back empty"
    return True, ""


def fallback(tool_results: list[dict]) -> str:
    """A plain sentence per tool, built only from the rows."""
    out = []
    for r in tool_results:
        tool, outcome, d = r.get("tool"), r.get("outcome"), r.get("data") or {}
        if outcome in ("not_in_graph", "unknown_entity", "not_permitted", "needs_approval"):
            out.append(f"{tool}: {r.get('reason')}")
        elif tool == "customer_trace":
            kinds = [i["kind"] for i in d.get("timeline", [])]
            out.append(f"Customer {d.get('customer')} ({d.get('region')}): {kinds.count('order')} orders, "
                       f"{kinds.count('ticket')} tickets, {kinds.count('refund')} refunds.")
        elif tool == "open_loops":
            out.append(f"Open: {len(d.get('open_tickets', []))} tickets, {len(d.get('open_promises', []))} promises; "
                       f"broken promises: {len(d.get('broken_promises', []))}; late parcels: "
                       f"{len(d.get('late_in_transit', []))}.")
        elif tool == "related_issues" and d.get("shared"):
            s = d["shared"][0]
            out.append(f"{s['other_tickets']} other tickets in {d.get('days')} days went through {s['id']}.")
        elif tool == "cluster_incidents" and d.get("clusters"):
            c = d["clusters"][0]
            out.append(f"{c['tickets']} {c['issue']} tickets cluster at {c['root_hub']}.")
        elif tool == "trace_decisions":
            for dec in d.get("decisions", []):
                for a in dec["assumptions"]:
                    if a.get("status") == "broken":
                        link = f", linked to {a['linked']} ({a['basis']})" if a.get("linked") else ""
                        out.append(f"{dec['decision']} rests on {a['assumption']}: {a['value']} vs {a['op']} "
                                   f"{a['threshold']}, broken{link}.")
        elif tool == "decision_impact":
            out.append(f"{d.get('decision')}: keystone rank {d.get('keystone_rank')}, "
                       f"{len(d.get('dependent_decisions', []))} dependent decisions, "
                       f"{d.get('parcels_in_transit')} parcels in transit, "
                       f"{len(d.get('customers_at_risk', []))} customers at risk.")
        elif tool == "prelaunch_check":
            for w in d.get("warnings", []):
                reroute = f"; reroute via {w['reroute']['hub']}" if w.get("reroute") else ""
                out.append(f"{w['campaign']} starts in {w['starts_in_days']} days through {w['hub']}, "
                           f"which has broken assumptions{reroute}.")
    return " ".join(out) or "No tool returned anything to report."
