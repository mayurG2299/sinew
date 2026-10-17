"""Company documents: find passages by words and by what they are about, and pick the sources for an answer.

A passage is linked in the graph to the hubs, couriers, decisions and campaigns it talks about, so "sources for
this answer" is a graph question: which passages mention the things the answer's tool results touched.
A document with an audience is shown only to those roles; others are told how many passages were held back.
"""

import json
import re
import time

from sinew.db import graph
from sinew.tools import guard
from sinew.tools.answer import Answer, unknown

FIELDS = "p.id, p.heading, p.text_clean, d.id, d.title, d.kind, d.audience, d.written_at"
ISSUE_TOPICS = {"refund_status": "refund", "refund": "refund", "late_delivery": "late delivery",
                "delivery": "delivery", "damaged": "damaged return refund", "wrong_item": "return refund",
                "product_issue": "return refund"}
DECISION_TOOLS = {"trace_decisions", "decision_impact", "prelaunch_check", "cluster_incidents"}
TOPICS = ("refund", "late", "return", "damaged", "capacity", "sale", "delivery", "escalat", "incident", "approve")


def _query(text: str) -> str:
    """Words only, joined as OR, for the full-text index (no operators from the user's text)."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text.lower())][:12]
    return "|".join(words)


def _rows(tenant: str, text: str | None, about: list[str]) -> dict[str, dict]:
    g = graph(tenant)
    found: dict[str, dict] = {}

    def add(rows, score_of):
        for pid, heading, body, did, title, kind, audience, written, score in rows:
            hit = found.setdefault(pid, {"passage": pid, "heading": heading, "text": body, "doc": did, "title": title,
                                         "kind": kind, "audience": audience or [], "written_at": written, "score": 0.0})
            hit["score"] += score_of(score)

    if text and _query(text):
        add(g.ro_query("CALL db.idx.fulltext.queryNodes('Passage', $q) YIELD node AS p, score "
                       f"MATCH (p)-[:PART_OF]->(d:Doc) RETURN {FIELDS}, score", {"q": _query(text)}).result_set,
            lambda s: float(s))
    if about:
        add(g.ro_query(f"MATCH (p:Passage)-[:MENTIONS]->(x) WHERE x.id IN $about MATCH (p)-[:PART_OF]->(d:Doc) "
                       f"RETURN {FIELDS}, count(x)", {"about": about}).result_set,
            lambda n: 2.0 * n)
    return found


def _allowed(v: guard.Viewer, hits: list[dict]) -> tuple[list[dict], int]:
    shown = [h for h in hits if not h["audience"] or v.role in h["audience"]]
    return shown, len(hits) - len(shown)


def search_docs(tenant: str, user_id: str, text: str | None = None, about: list[str] | None = None,
                limit: int = 5) -> Answer:
    start = time.perf_counter()
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return unknown("search_docs", f"user {user_id}")
    hits = sorted(_rows(tenant, text, about or []).values(), key=lambda h: -h["score"])
    shown, held = _allowed(v, hits)
    hidden = [{"kind": "passage", "count": held, "reason": "documents shared only with other roles"}] if held else []
    ms = round((time.perf_counter() - start) * 1000, 1)
    if not shown:
        return Answer("search_docs", "not_in_graph", reason="no company document matches", hidden=hidden, ms=ms)
    data = [{k: h[k] for k in ("passage", "doc", "title", "kind", "heading", "text")} for h in shown[:limit]]
    return Answer("search_docs", "answered_path", data=data, hidden=hidden, ms=ms,
                  paths=[[d["passage"], d["doc"]] for d in data])


def sources(tenant: str, user_id: str, results: list[dict], question: str = "", limit: int = 3,
            answer: str = "") -> list[dict]:
    """The document passages behind an answer: those about the hubs, couriers, decisions and campaigns the
    answer's tool results touched, plus those matching its topic words. Only what this person may read."""
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return []
    blob = json.dumps(results, default=str).lower()
    # Hubs and couriers lead to documents only when the answer is about decisions; a customer's parcel passing
    # through Hub W2 doesn't make the courier contract a source for their refund question.
    about_decisions = any(r.get("tool") in DECISION_TOOLS for r in results)
    about = set(re.findall(r"\b(?:hub|courier|dec)-[a-z0-9-]*[a-z0-9]\b" if about_decisions else r"\bdec-[a-z0-9-]*[a-z0-9]\b", blob))
    if about_decisions:
        campaigns = {c for c, in graph(tenant).ro_query("MATCH (c:Campaign) RETURN c.id").result_set}
        about |= {c for c in campaigns if re.search(rf"\b{re.escape(c)}\b", blob)}
    # Topic words come from what the case is about (issue types, refund or delivery kinds) and the question,
    # never from field names like "late_hours" that every record carries.
    kinds = set(re.findall(r'"(?:issue|issue_type|kind|promise)": "([a-z_]+)"', blob))
    words = " ".join(ISSUE_TOPICS.get(k, "") for k in kinds) + " " + question.lower()
    topics = " ".join(t for t in TOPICS if t in words)
    hits = sorted(_rows(tenant, topics or None, sorted(about)).values(), key=lambda h: -h["score"])
    shown, _ = _allowed(v, hits)
    # Passages the AI itself searched and read come first, in its order; then the ones the graph links to.
    used = [d for r in results if r.get("tool") == "search_docs" for d in (r.get("data") or [])]
    if any(r.get("tool") == "search_docs" for r in results):
        shown = []  # the AI searched the documents: its own hits are the sources, nothing loosely related
    candidates = {d["passage"]: d for d in used}
    for h in shown:
        candidates.setdefault(h["passage"], h)
    if answer:  # keep the passages the answer actually draws on, most-used first
        said = _words(answer)
        scored = sorted(((len(_words(c["text"] + " " + c["heading"]) & said), i, c) for i, c in enumerate(candidates.values())),
                        key=lambda x: (-x[0], x[1]))
        picked = [c for n, _, c in scored if n >= 3]
    else:
        picked = list(candidates.values())
    return [{k: h[k] for k in ("passage", "doc", "title", "kind", "heading", "text")} for h in picked[:limit]]


STOP = {"that", "this", "with", "from", "have", "will", "must", "they", "their", "there", "what", "when", "which",
        "your", "into", "than", "then", "them", "were", "been", "also", "only", "each", "more", "about", "after"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9%$]{4,}", text.lower()) if w not in STOP}
