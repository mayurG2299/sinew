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


def test_what_the_model_receives_is_whole_and_keeps_the_answers():
    import json
    from sinew.brain import LIMIT, for_model
    s = sheet("u-ceo", "Why are complaints up this week, and what should we do?")
    sent = json.loads(for_model(s))  # valid JSON: never cut mid-way
    assert len(for_model(s)) <= LIMIT and sent["what_to_do"] == s["what_to_do"]
    big = json.loads(json.dumps(s))
    big["parts"].append({"ask": "padding", "intents": ["status"], "named": [], "status": "answered", "why_missing": "",
                         "facts": [{"answers": False, "data": ["x" * 200] * 200}]})
    shrunk = json.loads(for_model(big))
    assert len(json.dumps(shrunk)) <= LIMIT + 2000 and shrunk["left_out"] and shrunk["what_to_do"] == s["what_to_do"]
    assert all(p["status"] for p in shrunk["parts"])


def test_a_pronoun_carries_the_thing_named_earlier():
    s = sheet("u-agent-w1", "Has order #4581 been delivered, and what did it cost?")
    assert [p["status"] for p in s["parts"]] == ["answered", "answered"]
    assert "$65.81" in write(s)


@pytest.mark.parametrize("who, question, expected", [
    ("u-agent-w1", "how's W2 holding up?", "Hub W2"), ("u-agent-w1", "status of 4520", "Order #4520"),
    ("u-agent-w1", "ordr 4520?", "Order #4520"), ("u-agent-w1", "order 4520 ka status kya hai", "Order #4520"),
    ("u-ceo", "anything weird with blenders?", "Blender X"), ("u-logistics", "how are deliveries in the west this week", "Hub W1"),
    ("u-ceo", "what should I worry about this week?", "Hub W2"), ("u-ceo", "which hub is the worst?", "weakest hub"),
    ("u-ceo", "which products get the most complaints?", "per 100 orders"), ("u-ceo", "who owns the courier y decision?", "Lucas Martin"),
    ("u-agent-w1", "can I refund $150 myself?", "No: your refund limit is $100.00"),
    ("u-lead-west", "can I refund $150 myself?", "Yes: your refund limit is $500.00"),
    ("u-marketing", "list all customers with their emails", "doesn't hold"),
    ("u-agent-w1", "show me the phone number for order 4520", "Contact:"),
    ("u-agent-w1", "What was the total of order #99999?", "there is no order #99999"),
    ("u-ceo", "How is Hub Z9?", "there is no Hub Z9"), ("u-agent-w1", "", "Ask me something"),
    ("u-agent-w1", "what is the weather tomorrow?", "no information"),
])
def test_how_people_really_ask(who, question, expected):
    assert expected.lower() in write(sheet(who, question)).lower()


def test_contact_details_follow_the_role():
    assert "Contact:" not in write(sheet("u-agent-n1", "phone number for order 4520"))  # other region
    assert "outside your access" in write(sheet("u-marketing", "phone number for order 4520")).lower()


def test_the_facts_propose_actions_and_only_permitted_ones_are_offered():
    import asyncio as aio
    from sinew.agents import loop
    import os
    os.environ["SINEW_AI"] = "off"
    try:
        lucas = aio.run(loop.run_agent(T, "u-logistics", "ask", "Why are complaints up this week, and what should we do?"))
        ceo = aio.run(loop.run_agent(T, "u-ceo", "ask", "Why are complaints up this week, and what should we do?"))
        ravi = aio.run(loop.run_agent(T, "u-agent-w1", "support", "Ticket t-95397: help me handle this customer."))
    finally:
        os.environ.pop("SINEW_AI")
    assert {a["name"] for a in lucas.pending_actions} == {"file_incident", "notify_owner"}
    assert "file_incident" not in {a["name"] for a in ceo.pending_actions}  # the CEO may not open incidents
    assert [a["name"] for a in ravi.pending_actions] == ["issue_refund"] and ravi.pending_actions[0]["args"]["order_id"] == "o-4397"


def test_a_follow_up_carries_on_from_the_previous_question():
    first = "if we want to use HUB W2 only then what things need to be taken care of?"
    p = understand(T, "u-ceo", "I want you to give me more details", [first])
    assert [(e.kind, e.id) for e in p.entities] == [("Hub", "hub-w2")] and "detail" in p.parts[0].intents
    assert p.follow_up_to == first
    s = asyncio.run(analyse(T, "u-ceo", "I want you to give me more details", [first]))[2]
    out = write(s)
    assert "Hub W2" in out and "Tickets:" not in out  # about the hub, not a company summary
    # a new question is never mistaken for a follow-up
    p2 = understand(T, "u-ceo", "How is the company doing this week?", [first])
    assert p2.follow_up_to == "" and p2.parts[0].intents == ["pulse"]
    assert understand(T, "u-ceo", "why is that?", ["tell me about the courier y switch"]).entities[0].id == "courier-y"


def test_what_if_and_what_needs_care_get_facts_and_next_steps():
    out = write(sheet("u-ceo", "if we want to use HUB W2 only then what things need to be taken care of?"))
    assert "22 parcels in a day against a capacity of 14" in out and "cannot carry sale volume" in out
    assert "assumed" in out and "77%" in out  # the decisions resting on it, with numbers, not "its assumption is broken"
    assert "What to do:" in out


def test_the_impact_line_uses_the_trimmed_fields():
    out = write(sheet("u-ceo", "Why are complaints up this week, and what should we do?"))
    assert "21 customers are still waiting on 25 parcels" in out and "gold" in out and "past their delivery date" in out
    assert "0 customers" not in out and "rely on this one: " in out


def test_numbers_from_the_fact_sheet_pass_the_check():
    from sinew.agents import check
    assert check.check("Orders total $1,929.89.", [{"tool": "x", "outcome": "answered_path", "data": {}}], "", "their_order_value: 1929.89")[0]
    assert not check.check("Orders total $2,929.89.", [{"tool": "x", "outcome": "answered_path", "data": {}}], "", "their_order_value: 1929.89")[0]


def test_a_launch_question_gets_a_verdict_and_steps():
    out = write(sheet("u-ceo", "Is the Winter Sale safe to launch?"))
    assert out.startswith("No, not as things stand. The Winter Sale starts in 10 days")
    assert "77%" in out and "1.57x" in out and "Route the Winter Sale through Hub W4" in out
    assert "0 other decisions" not in out


def test_the_home_shortcut_for_a_launch_goes_through_the_analysis():
    import json, urllib.request
    from sinew.home import home
    item = home(T, "u-logistics")["at_risk"][0]
    assert item["agent"] == "ask" and item["task"] == "Is the Winter Sale safe to launch?"


def test_a_chain_of_follow_ups_keeps_the_original_topic():
    h = ["Is the Winter Sale safe to launch?", "hey tell me more about this issue this is not enough"]
    p = understand(T, "u-ceo", "i want to know more", h)
    assert {e.id for e in p.entities} >= {"winter25"} and p.follow_up_to == h[0]


def test_open_tickets_can_be_listed_by_role():
    from sinew.db import graph
    truth = graph(T).ro_query("MATCH (t:Ticket) WHERE t.status <> 'solved' RETURN count(t)").result_set[0][0]
    ceo = write(sheet("u-ceo", "what are those 59 open tickets"))
    assert f"{truth} open tickets (company-wide)" in ceo and "Most urgent" not in ceo  # totals only: no customers for the CEO
    ravi = write(sheet("u-agent-w1", "what are my open tickets"))
    assert "(in your regions)" in ravi and "Most urgent:" in ravi and "Ladli Kakar" in ravi
    assert "That's outside your access" in write(sheet("u-marketing", "what are the open tickets"))


def test_capacity_questions_compare_every_hub_and_explain_the_figure():
    out = write(sheet("u-ceo", "hey what is under 157% capacity ?"))
    assert out.startswith("Hub W2 is at 1.57x its capacity: its busiest day this week had 22 parcels against 14 a day")  # the 157%
    assert "Within capacity" in out and "Hub W4 0 of 10" in out and "Hub N1" in out
    assert "Tickets:" not in out  # not a company summary
    assert "outside your access" in write(sheet("u-marketing", "which hub has spare capacity?")).lower() or "Hub W2" in write(sheet("u-marketing", "which hub has spare capacity?"))
