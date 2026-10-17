"""Route a question to the graph walks that answer it, without AI.

The question names things: an order (#4581), a hub (Hub W2), a decision (its title words), a campaign (FEST40),
or a topic (cost, refund policy, the state of the company). Each named thing is a starting node; the router picks
the walk that starts there. The AI later only writes the sentence from what these walks returned.

    route("What was the total of order #4581?") -> [("order_detail", {"order": "#4581"})]
"""

import re

from sinew.db import graph

DOC_WORDS = r"polic|rule|limit|approve|refund|return|cost|spend|budget|price|contract|agreement|plan|notes|standard|how fast|how do we|leave"
PULSE_WORDS = r"how is the company|how are we doing|state of the company|this week overall|overview|summary for me|company doing"
WHY_WORDS = r"\bwhy\b.*\b(complain|late|delay|up)\b|what('s| is) behind|root cause"
GENERIC = {"courier", "cost", "costs", "deliveries", "delivery", "customers", "hub", "sale", "day"}
COUNT_WORDS = r"how many (support )?tickets|tickets did we get|on-time rate|on time rate|revenue|orders this week"


def _decisions(tenant: str) -> list[tuple[str, str]]:
    return graph(tenant).ro_query("MATCH (d:Decision) RETURN d.id, d.title").result_set


def route(tenant: str, question: str) -> list[tuple[str, dict]]:
    q = question.lower()
    calls: list[tuple[str, dict]] = []
    for n in re.findall(r"#\s?(\d{3,6})|\border\s+(\d{3,6})", q):
        calls.append(("order_detail", {"order": "#" + (n[0] or n[1])}))
    for letter, num in re.findall(r"\bhub\s?-?([a-z])\s?(\d+)", q):
        calls.append(("hub_status", {"hub": f"Hub {letter.upper()}{num}"}))
    # a decision is named when most of its distinctive title words appear in the question
    words = set(re.findall(r"[a-z0-9]{3,}", q))
    for did, title in _decisions(tenant):
        tw = set(re.findall(r"[a-z0-9]{3,}", title.lower())) - {"the", "and", "west", "region", "run", "off", "for"}
        hit = tw & words
        specific = hit - GENERIC  # "courier" and "cost" alone don't name a decision; "switch" or "winter" do
        if specific and (len(hit) / len(tw) >= 0.6 or len(hit) >= 2):
            calls.append(("decision_detail", {"decision": did}))
    if re.search(WHY_WORDS, q):
        calls += [("cluster_incidents", {}), ("prelaunch_check", {})]
    if re.search(PULSE_WORDS, q) or re.search(COUNT_WORDS, q):
        calls.append(("company_pulse", {}))
    if re.search(DOC_WORDS, q) and not any(c[0] == "order_detail" for c in calls):
        calls.append(("search_docs", {"text": question}))
    return calls


def follow_up(name: str, result: dict) -> list[tuple[str, dict]]:
    """The second step of a walk that depends on the first: a complaint cluster leads to its root hub's decisions."""
    if name == "cluster_incidents" and result.get("outcome") == "answered_path":
        root = (result["data"].get("clusters") or [{}])[0].get("root_hub")
        return [("trace_decisions", {"hub_id": root})] if root else []
    return []
