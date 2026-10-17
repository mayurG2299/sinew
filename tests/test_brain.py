"""The analysis layer, stage by stage, without AI: understand, break down, walk, reconcile, write."""

import asyncio

import pytest

from sinew.brain import analyse, understand, walks, write

T = "sandbox"


@pytest.fixture(scope="module", autouse=True)
def graph_(northwind_copy):
    return northwind_copy


def linked(q, user="u-ceo"):
    return {(e.kind, e.id) for e in understand(T, user, q).entities}


@pytest.mark.parametrize("question, entity", [
    ("What was the total of order #4581?", ("Order", "o-4581")), ("order 4520 status", ("Order", "o-4520")),
    ("Is Hub W2 coping?", ("Hub", "hub-w2")), ("How is Courier Y doing?", ("Courier", "courier-y")),
    ("How did FEST40 do?", ("Campaign", "fest40")), ("How is the Festive Flash Sale going?", ("Campaign", "fest40")),
    ("What did we decide about the backup courier?", ("Decision", "dec-drop-backup")),
    ("Any complaints about the Knife Set?", ("Product", "knife-set")), ("Is batch B7 a problem?", ("Batch", "b7")),
    ("Ticket t-90520: help me", ("Ticket", "t-90520")),
])
def test_names_in_a_question_are_linked_to_real_nodes(question, entity):
    assert entity in linked(question)


def test_made_up_things_are_not_linked():
    assert linked("What about order #99999 and Hub Z9?") == set()


def test_time_windows_and_parts():
    p = understand(T, "u-ceo", "How is the company doing this month?")
    assert p.window["days"] == 30 and p.parts[0].intents == ["pulse"]
    p = understand(T, "u-ceo", "Why are complaints up this week, and what should we do?")
    assert [x.intents for x in p.parts] == [["why"], ["what_to_do"]]
    assert understand(T, "u-ceo", "What happened yesterday?").window["label"] == "yesterday"


def test_each_part_walks_from_what_it_names():
    p = understand(T, "u-marketing", "How is the FEST40 sale doing and is Hub W2 coping?")
    assert [w[0][0] for w in walks(p)] == ["decision_detail", "hub_status"]


def sheet(user, q):
    return asyncio.run(analyse(T, user, q))[2]


def test_reconcile_tells_no_access_from_no_data():
    assert sheet("u-marketing", "What does Courier Y cost per parcel?")["parts"][0]["status"] == "no_access"
    assert sheet("u-cmo", "What does Courier Y cost per parcel?")["parts"][0]["status"] == "answered"
    assert sheet("u-agent-w1", "What is our office leave policy?")["parts"][0]["status"] == "no_data"
    assert sheet("u-contractor-1", "Why are complaints up this week?")["parts"][0]["status"] == "no_access"


def test_the_written_answer_follows_from_the_facts():
    why = write(sheet("u-ceo", "Why are complaints up this week, and what should we do?"))
    assert "Hub W2" in why and "77%" in why and "not proof of cause" in why
    assert "Route the Winter Sale through Hub W4" in why and "What to do:" in why
    b7 = write(sheet("u-ceo", "Is batch B7 causing problems?"))
    assert "Batch B7" in b7 and "per 100" in b7
    assert write(sheet("u-marketing", "What does Courier Y cost per parcel?")) == "That's outside your access."
    contractor = write(sheet("u-contractor-1", "Ticket t-90520: help me handle this customer."))
    assert "[NAME]" not in contractor and "Payment details are for staff only" in contractor
