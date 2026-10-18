"""The agent loop with a scripted fake model: no API calls, deterministic."""

import asyncio

import pytest

from sinew.agents import check, loop
from sinew.agents.llm import LLMUnavailable, Turn


@pytest.fixture(scope="module", autouse=True)
def _data(northwind_copy):
    yield


@pytest.fixture(autouse=True)
def replays(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "REPLAYS", tmp_path)


class Scripted:
    """Plays back tool calls, then a final answer."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def start(self, system, tools, task):
        self.tools = {t["name"] for t in tools}

    async def next(self):
        if not self.turns:
            raise LLMUnavailable("script ended")
        t = self.turns.pop(0)
        if isinstance(t, Exception):
            raise t
        return t

    def add_results(self, results):
        self.seen.extend(results)


def ai(r):
    """The steps the model took itself (the analysis layer's graph walks come first)."""
    return [s for s in r.steps if s.get("by") != "graph"]


def run(llm, agent="support", user="u-agent-w1", task="Ticket t-90520: parcel late"):
    return asyncio.run(loop.run_agent("sandbox", user, agent, task, llm=llm))


def test_tools_run_and_a_checked_answer_is_kept(monkeypatch):
    monkeypatch.setattr(check, "coverage", lambda d, a: (1.0, []))  # this test is about something else
    r = run(Scripted([Turn(calls=[{"name": "related_issues", "args": {"ticket_id": "t-90520"}}]),
                      Turn(text="Others are affected through hub-w2.")]))
    assert r.answer_source == "model" and ai(r)[0]["outcome"] == "answered_path"


def test_destructive_tool_waits_for_a_person():
    r = run(Scripted([Turn(calls=[{"name": "issue_refund", "args": {"order_id": "o-4500", "amount": 10}}]),
                      Turn(text="I have prepared a refund for o-4500 for you to confirm.")]))
    assert r.pending_actions == [{"name": "issue_refund", "args": {"order_id": "o-4500", "amount": 10}}]
    assert ai(r)[0]["outcome"] == "pending_confirmation"


def test_tool_outside_the_agents_set_is_refused():
    r = run(Scripted([Turn(calls=[{"name": "notify_owner", "args": {"decision_id": "dec-courier-y", "message": "x"}}]),
                      Turn(text="Done.")]))
    assert ai(r)[0]["outcome"] == "not_permitted" and r.pending_actions == []


def test_made_up_name_is_replaced_by_a_sentence_from_the_rows():
    r = run(Scripted([Turn(calls=[{"name": "related_issues", "args": {"ticket_id": "t-90520"}}]),
                      Turn(text="This is all because of hub-w9.")]))
    assert r.answer_source == "rows" and "hub-w9" in r.check_failed and "hub-w9" not in r.answer


def test_causal_wording_about_decisions_is_rejected():
    r = run(Scripted([Turn(calls=[{"name": "trace_decisions", "args": {"hub_id": "hub-w2"}}]),
                      Turn(text="dec-courier-y broke because dec-flash-sale overloaded hub-w2.")]),
            agent="pattern", user="u-lead-west", task="why")
    assert r.answer_source == "rows" and "not causes" in r.check_failed


def test_model_down_answers_from_the_graph_now():
    # a fresh answer written from today's graph beats a saved answer from earlier
    r = run(Scripted([LLMUnavailable("429 quota")]))
    assert r.answer_source == "graph" and r.answer == check.paragraphs(r.draft) and "This customer has" in r.answer


def test_model_down_and_nothing_to_draft_falls_back_to_the_last_good_run():
    good = run(Scripted([Turn(text="Nothing more to add.")]), task="zz qq")
    again = run(Scripted([LLMUnavailable("429 quota")]), task="zz qq")
    assert again.answer_source in ("replay", "graph", "rows")


def test_check_accepts_percentages_and_rounding():
    results = [{"tool": "trace_decisions", "outcome": "answered_path", "data": {"value": 0.7117, "threshold": 0.9}}]
    assert check.check("On time is 71% against 90%.", results)[0]
    assert not check.check("On time is 64%.", results)[0]


def test_plain_names_are_checked_like_ids():
    results = [{"tool": "customer_trace", "outcome": "answered_path",
                "data": {"order": "o-4520", "hub": "hub-w2", "courier": "courier-y", "late_hours": 30}}]
    assert check.check("Order #4520 is 30 h late at Hub W2 with Courier Y.", results)[0]
    assert not check.check("Order #4999 is late.", results)[0]
    assert not check.check("It is stuck at Hub W9.", results)[0]
    assert not check.check("Courier Z has it.", results)[0]


def test_ratios_may_be_written_as_percentages():
    results = [{"tool": "prelaunch_check", "outcome": "answered_path", "data": {"value": 1.5714}}]
    assert check.check("Hub load is 157% of capacity.", results)[0]
    assert not check.check("Hub load is 175% of capacity.", results)[0]


def test_plain_names_written_in_documents_count():
    results = [{"tool": "search_docs", "outcome": "answered_path", "data": [{"text": "Courier Y runs Hub W2"}]}]
    assert check.check("Courier Y runs Hub W2.", results)[0]


def test_numbers_with_thousands_separators_are_one_number():
    results = [{"tool": "company_pulse", "outcome": "answered_path", "data": {"revenue": 17949.49, "spend": 3500}}]
    assert check.check("Revenue was $17,949.49 and spend was $3,500.", results)[0]
    assert not check.check("Revenue was $18,949.49.", results)[0]


class Repairable(Scripted):
    """A model that can take Sinew's correction message."""

    def add_user(self, text):
        self.seen.append(("correction", text))


def test_one_corrected_rewrite_is_checked_and_kept(monkeypatch):
    monkeypatch.setattr(check, "coverage", lambda d, a: (1.0, []))  # this test is about something else
    llm = Repairable([Turn(calls=[{"name": "trace_decisions", "args": {"hub_id": "hub-w2"}}]),
                      Turn(text="Courier Y broke because of the sale."),
                      Turn(text="The complaints went through Hub W2.")])
    r = run(llm, agent="pattern", user="u-lead-west", task="why")
    assert r.answer_source == "model" and r.answer == "The complaints went through Hub W2."
    assert "not causes" in r.repaired and any(k == "correction" for k, _ in llm.seen)


def test_a_rewrite_that_still_breaks_a_rule_falls_back_to_the_rows():
    r = run(Repairable([Turn(calls=[{"name": "trace_decisions", "args": {"hub_id": "hub-w2"}}]),
                        Turn(text="It broke because of the sale."), Turn(text="It broke due to the sale.")]),
            agent="pattern", user="u-lead-west", task="why")
    assert r.answer_source == "rows" and "not causes" in r.check_failed


def test_an_action_the_person_cannot_take_is_never_offered():
    # the CEO may read operations but may not open incidents: no button, and the model is told so
    r = run(Scripted([Turn(calls=[{"name": "file_incident", "args": {"title": "W2 delays", "ticket_ids": ["t-90520"],
                                                                      "root_hub": "hub-w2"}}]),
                      Turn(text="The complaints went through hub-w2.")]),
            agent="pattern", user="u-ceo", task="why")
    assert "file_incident" not in {a["name"] for a in r.pending_actions} and ai(r)[0]["outcome"] == "not_permitted"


def test_only_the_maker_or_a_lead_can_confirm_a_commitment():
    from sinew.tools import actions
    from sinew.db import graph
    row = graph("sandbox").ro_query("MATCH (p:Promise)-[:MADE_BY]->(u:User {id: 'u-agent-w2'}) RETURN p.id LIMIT 1").result_set
    assert row, "needs a commitment made by u-agent-w2"
    assert actions.confirm_promise("sandbox", "u-agent-w1", row[0][0]).outcome == "not_permitted"
    assert actions.precheck("sandbox", "u-lead-west", "confirm_promise", {"promise_id": row[0][0]}) is None


def test_a_long_history_keeps_the_newest_events_for_the_model():
    timeline = [{"kind": "order", "id": f"o-{i}", "at": i, "pad": "x" * 400} for i in range(100)]
    text = loop.for_model({"tool": "customer_trace", "data": {"timeline": timeline}, "paths": [["a", "b"]] * 500})
    assert '"paths"' not in text and "o-99" in text and len(text) <= loop.RESULT_CHARS


def test_when_the_ai_cannot_start_the_answer_still_comes_from_the_graph(monkeypatch):
    monkeypatch.setenv("SINEW_AI", "off")
    r = asyncio.run(loop.run_agent("sandbox", "u-agent-w1", "ask", "What was the total of order #4581?"))
    assert r.answer_source == "graph" and "$65.81" in r.answer and "unavailable" not in r.answer.lower()


def test_a_rewrite_that_drops_the_graphs_numbers_is_replaced_by_the_draft():
    assert check.coverage("Hub W2 is at 1.57x: 22 parcels against 14 a day.", "It is at 157%, 22 parcels vs 14.")[0] == 1.0
    share, left = check.coverage("Hub W2 is at 1.57x: 22 parcels against 14 a day. Hub N1 1.80x.", "Hubs within capacity are fine.")
    assert share < 0.2 and "22" in left
    assert check.coverage("No access.", "No access.")[0] == 1.0  # nothing numeric to keep


def test_the_loop_uses_the_draft_when_the_rewrite_drops_the_facts():
    r = run(Scripted([Turn(text="Everything looks fine here.")]), agent="ask", user="u-ceo",
            task="Why are complaints up this week, and what should we do?")
    assert r.answer_source == "rows" and "left out facts" in r.check_failed and r.answer == check.paragraphs(r.draft)
    assert "Hub W2" in r.answer and "77%" in r.answer


def test_totals_and_shares_derived_from_the_facts_are_allowed_but_made_up_numbers_are_not():
    res = [{"tool": "graph_query", "outcome": "answered_path", "data": {"columns": ["n", "customers"], "rows": [[3, 9], [2, 19], [1, 24]]}}]
    assert check.check("28 customers have more than one open ticket.", res)[0]  # 9 + 19
    assert check.check("9 of 52 customers, about 17%, have three.", res)[0]  # 9 / (9 + 19 + 24)
    assert not check.check("31 customers have more than one open ticket.", res)[0]


def test_uses_rows_tells_a_rewrite_that_kept_the_finding_from_one_that_dropped_it():
    rows = [["Ladli Kakar", "3 Oct"], ["Reece Magar", "8 Oct"]]
    assert check.uses_rows(rows, "Ladli Kakar has waited longest.")
    assert not check.uses_rows(rows, "Sinew has no information about it.")
    assert check.uses_rows([["courier-y", 4.2]], "Courier Y costs $4.20 per parcel.")
    assert not check.uses_rows([["courier-y", 4.2]], "Sinew has no document about leave policies.")
    assert check.uses_rows([[0, 1]], "anything")  # nothing comparable came back


class PlansThenWords(Scripted):
    """A model that plans a graph walk (cost of Courier Y) and then words the answer however the test says."""

    async def plan(self, system, user):
        return {"parts": [{"ask": "what does courier y cost per parcel", "intents": ["cost"],
                           "entities": [{"kind": "Courier", "id": "courier-y"}],
                           "query": {"match": [{"label": "Courier", "id": "courier-y"}, {"rel": "FOR", "dir": "in", "label": "CostLine"}],
                                     "return": [{"agg": "avg", "of": "CostLine", "prop": "amount", "as": "amount"}]}}]}


def test_a_rewrite_that_throws_away_what_the_walk_found_is_replaced_by_the_graphs_draft():
    q = "What does Courier Y cost per parcel?"
    bad = run(PlansThenWords([Turn(text="Sinew has no information about that.")]), agent="ask", user="u-cmo", task=q)
    assert bad.answer_source == "rows" and "4.2" in bad.answer and "mentions nothing" in bad.check_failed
    good = run(PlansThenWords([Turn(text="Courier Y costs $4.20 per parcel.")]), agent="ask", user="u-cmo", task=q)
    assert good.answer_source == "model" and "4.20" in good.answer


def test_the_graphs_draft_is_split_into_paragraphs_so_a_page_does_not_run_it_together():
    draft = "Hub W2: 25 parcels.\nTickets: 54.\nDue by customer:\n- Ladli Kakar: 3 Oct\n- Reece Magar: 8 Oct\n\nDone."
    assert check.paragraphs(draft) == ("Hub W2: 25 parcels.\n\nTickets: 54.\n\nDue by customer:\n\n- Ladli Kakar: 3 Oct\n- Reece Magar: 8 Oct\n\nDone.")
    assert check.paragraphs("") == "" and check.paragraphs("one line") == "one line"


def test_mcp_over_http_serves_read_tools_only_as_the_person_in_the_url_and_nothing_without_the_secret():
    from starlette.testclient import TestClient
    from sinew.mcp_http import make_app
    secret = "s" * 32
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    def rpc(client, path, method, params=None, id_=1):
        return client.post(path, headers=headers, json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
    init = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}
    with TestClient(make_app("sandbox", ["u-cmo", "u-marketing"], secret)) as c:
        assert rpc(c, f"/wrong-secret/u-cmo/mcp", "initialize", init).status_code == 404
        assert rpc(c, f"/{secret}/u-ceo/mcp", "initialize", init).status_code == 404  # a person that isn't served
        names = {t["name"] for t in rpc(c, f"/{secret}/u-cmo/mcp", "tools/list").json()["result"]["tools"]}
        assert {"graph_query", "company_pulse", "hub_status"} <= names
        assert not names & {"issue_refund", "record_promise", "confirm_promise", "file_incident", "notify_owner", "write_finding"}
        ask = {"name": "graph_query", "arguments": {"spec": {"match": [{"label": "Courier", "id": "courier-y"}, {"rel": "FOR", "dir": "in", "label": "CostLine"}],
                                                            "return": [{"agg": "avg", "of": "CostLine", "prop": "amount", "as": "amount"}]}, "ask": "cost"}}
        cmo = rpc(c, f"/{secret}/u-cmo/mcp", "tools/call", ask, 2).json()["result"]["content"][0]["text"]
        chloe = rpc(c, f"/{secret}/u-marketing/mcp", "tools/call", ask, 3).json()["result"]["content"][0]["text"]
        assert "answered_path" in cmo and "4.2" in cmo
        assert "not_permitted" in chloe and "4.2" not in chloe  # the same call, a different person's URL
