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
