"""Retrieval accuracy without AI, on the test copy of the graph: random questions are routed to graph walks,
run as the person asking, and the returned data must match independent Cypher (sinew/eval_retrieval.py)."""

import asyncio

import pytest

from sinew import eval_retrieval
from sinew.agents.router import route


@pytest.fixture(scope="module", autouse=True)
def graph_(northwind_copy):
    return northwind_copy


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_questions_retrieve_the_true_facts(seed):
    res = asyncio.run(eval_retrieval.main(seed, 8, "sandbox"))
    bad = [(r["who"], r["q"], r["expect"], r["tools"]) for r in res if not r["ok"]]
    assert not bad, bad


@pytest.mark.parametrize("question, first", [
    ("What was the total of order #4581?", "order_detail"), ("Has order 4520 been delivered?", "order_detail"),
    ("How many customers are waiting at Hub W2?", "hub_status"), ("Tell me about the courier Y switch", "decision_detail"),
    ("How is the company doing this week?", "company_pulse"), ("What does Courier Y cost per parcel?", "search_docs"),
    ("Why are complaints up this week?", "cluster_incidents"),
])
def test_questions_start_at_the_node_they_name(question, first):
    assert route("sandbox", question)[0][0] == first
