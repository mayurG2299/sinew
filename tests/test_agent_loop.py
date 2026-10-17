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


def run(llm, agent="support", user="u-agent-w1", task="Ticket t-90520: parcel late"):
    return asyncio.run(loop.run_agent("sandbox", user, agent, task, llm=llm))


def test_tools_run_and_a_checked_answer_is_kept():
    r = run(Scripted([Turn(calls=[{"name": "related_issues", "args": {"ticket_id": "t-90520"}}]),
                      Turn(text="Others are affected through hub-w2.")]))
    assert r.answer_source == "model" and r.steps[0]["outcome"] == "answered_path"


def test_destructive_tool_waits_for_a_person():
    r = run(Scripted([Turn(calls=[{"name": "issue_refund", "args": {"order_id": "o-4500", "amount": 10}}]),
                      Turn(text="I have prepared a refund for o-4500 for you to confirm.")]))
    assert r.pending_actions == [{"name": "issue_refund", "args": {"order_id": "o-4500", "amount": 10}}]
    assert r.steps[0]["outcome"] == "pending_confirmation"


def test_tool_outside_the_agents_set_is_refused():
    r = run(Scripted([Turn(calls=[{"name": "notify_owner", "args": {"decision_id": "dec-courier-y", "message": "x"}}]),
                      Turn(text="Done.")]))
    assert r.steps[0]["outcome"] == "not_permitted" and r.pending_actions == []


def test_made_up_name_is_replaced_by_a_sentence_from_the_rows():
    r = run(Scripted([Turn(calls=[{"name": "related_issues", "args": {"ticket_id": "t-90520"}}]),
                      Turn(text="This is all because of hub-w9.")]))
    assert r.answer_source == "rows" and "hub-w9" in r.check_failed and "hub-w9" not in r.answer


def test_causal_wording_about_decisions_is_rejected():
    r = run(Scripted([Turn(calls=[{"name": "trace_decisions", "args": {"hub_id": "hub-w2"}}]),
                      Turn(text="dec-courier-y broke because dec-flash-sale overloaded hub-w2.")]),
            agent="pattern", user="u-lead-west", task="why")
    assert r.answer_source == "rows" and "not causes" in r.check_failed


def test_model_down_falls_back_to_the_last_good_run():
    good = run(Scripted([Turn(calls=[{"name": "related_issues", "args": {"ticket_id": "t-90520"}}]),
                         Turn(text="Others are affected through hub-w2.")]))
    again = run(Scripted([LLMUnavailable("429 quota")]))
    assert again.answer_source == "replay" and again.answer == good.answer


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


def test_one_corrected_rewrite_is_checked_and_kept():
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
    assert r.pending_actions == [] and r.steps[0]["outcome"] == "not_permitted"


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
