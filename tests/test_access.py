"""Personas: every person reads only the areas their role may read (support, operations, marketing, finance).
The role -> area path is in the graph and in the queries, so nothing outside it reaches a tool result or the AI."""

import json

import pytest

from sinew.agents import check
from sinew.engine import pipeline
from sinew.mcp_server import build_server
from sinew.tools import docs, guard, impact, pulse, trace

T = "sandbox"
FINANCE_FIGURES = ("4.2", "4.8", "5.1", "3500", "3,500", "per_parcel", "spend", "revenue")


@pytest.fixture(scope="module", autouse=True)
def graph_(northwind_copy):
    return northwind_copy


def _sections(user):
    return {k for k in pulse.company_pulse(T, user).data if k in pulse.SECTIONS}


def test_each_role_gets_only_its_areas_in_the_company_pulse():
    assert _sections("u-marketing") == {"marketing", "operations"}
    assert _sections("u-cmo") == {"marketing", "operations", "finance"}
    assert _sections("u-contractor-1") == {"support"}
    assert _sections("u-ceo") == {"support", "operations", "marketing", "finance"}
    hidden = pulse.company_pulse(T, "u-marketing").hidden
    assert "finance" in hidden[0]["reason"] and "support" in hidden[0]["reason"]


def test_no_finance_figure_reaches_a_role_without_finance():
    blob = json.dumps(pulse.company_pulse(T, "u-marketing").as_dict())
    assert not any(f in blob for f in ("per_parcel", "spend", "revenue"))
    for result in (impact.trace_decisions(T, "hub-w2"), impact.prelaunch_check(T),
                   trace.customer_trace(T, "u-agent-w1", "t-90520")):
        assert not any(f in json.dumps(result.as_dict()) for f in ("per_parcel", "spend", "CostLine"))


def test_document_search_never_returns_another_areas_passages():
    marketer = docs.search_docs(T, "u-marketing", "courier cost per parcel")
    texts = json.dumps(marketer.as_dict())
    assert "$4.20" not in texts and "Cost sheet" not in texts
    assert sum(h["count"] for h in marketer.hidden) >= 1  # told something is held back, not what
    cmo = docs.search_docs(T, "u-cmo", "courier cost per parcel")
    assert any(d["title"] == "Cost sheet, October" for d in cmo.data)


def test_only_held_back_matches_is_not_permitted_not_missing():
    r = docs.search_docs(T, "u-contractor-1", "backup contract ends")  # only in operations meeting notes
    assert r.outcome == "not_permitted" and not r.data
    assert "backup" not in json.dumps(r.as_dict()).lower().replace("backup contract ends", "")


def test_sources_never_include_passages_the_person_cannot_read():
    results = [{"tool": "trace_decisions", "outcome": "answered_path", "data": {"hub": "hub-w2", "decision": "dec-courier-y"}}]
    marketer = docs.sources(T, "u-marketing", results, "what does courier y cost", answer="Courier Y costs per parcel west deliveries cost sheet")
    assert all(s["title"] != "Cost sheet, October" for s in marketer)


def test_skills_outside_a_role_are_refused_through_the_tool_server():
    import asyncio
    from mcp import Client

    async def call(user, tool, args):
        async with Client(build_server(T, user)) as c:
            return json.loads((await c.call_tool(tool, args)).content[0].text)

    assert asyncio.run(call("u-contractor-1", "cluster_incidents", {}))["outcome"] == "not_permitted"
    assert asyncio.run(call("u-marketing", "customer_trace", {"customer": "t-90520"}))["outcome"] == "not_permitted"
    assert asyncio.run(call("u-logistics", "cluster_incidents", {}))["outcome"] == "answered_path"


def test_a_role_with_no_policy_reads_nothing():
    pipeline.process(T, [{"event_id": "staff-intern", "type": "staff.upserted", "source": "roster", "occurred_at": 1,
                          "payload": {"user_id": "u-intern", "team_id": "team-marketing", "role": "intern"}}])
    v = guard.Viewer.load(T, "u-intern")
    assert v.areas == []
    assert pulse.company_pulse(T, "u-intern").outcome == "not_permitted"
    assert guard.gate(T, "u-intern", "trace_decisions")["outcome"] == "not_permitted"
    assert docs.search_docs(T, "u-intern", "refund").data in ({}, [], None)


def test_taking_an_area_away_takes_effect_at_once():
    def policy(areas, n):
        pipeline.process(T, [{"event_id": f"policy-mkt-{n}", "type": "access.policy", "source": "admin",
                              "occurred_at": 10 + n, "payload": {"role": "marketing_manager", "areas": areas}}])
    policy(["marketing"], 1)
    assert guard.gate(T, "u-marketing", "trace_decisions")["outcome"] == "not_permitted"
    policy(["marketing", "operations"], 2)
    assert guard.gate(T, "u-marketing", "trace_decisions") is None


@pytest.mark.parametrize("event", [
    {"type": "doc.passage", "payload": {"doc_id": "d", "title": "t", "kind": "policy", "passage_id": "d-1",
                                        "heading": "h", "order": 1, "text": "x", "area": "finanse"}},
    {"type": "access.policy", "payload": {"role": "agent", "areas": ["support", "everything"]}},
    {"type": "access.policy", "payload": {"role": "agent", "areas": "support"}},
    {"type": "cost.recorded", "payload": {"cost_id": "c", "kind": "courier_per_parcel", "subject_id": "courier-y",
                                          "amount": -1, "currency": "USD", "period_start": 1, "period_end": 2}},
    {"type": "cost.recorded", "payload": {"cost_id": "c", "kind": "salary", "subject_id": "courier-y",
                                          "amount": 1, "currency": "USD", "period_start": 1, "period_end": 2}},
])
def test_bad_access_or_finance_data_is_quarantined(event):
    r = pipeline.process(T, [{"event_id": f"bad-{event['type']}", "source": "admin", "occurred_at": 1, **event}])
    assert r.accepted == 0 and len(r.quarantined) == 1


def test_pulse_numbers_never_divide_by_zero():
    assert pulse._change(5, 0) is None and pulse._change(None, 3) is None and pulse._ratio(1, 0) is None
    assert pulse._change(6, 4) == 50.0


def test_the_check_accepts_rounded_changes_but_not_invented_ones():
    results = [{"tool": "company_pulse", "outcome": "answered_path", "data": {"orders_change_pct": 24.8}}]
    assert check.check("Orders are up 24% this week.", results)[0]
    assert check.check("Orders are up 25% this week.", results)[0]
    assert not check.check("Orders are up 31% this week.", results)[0]
