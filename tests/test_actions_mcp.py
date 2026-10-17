import asyncio
import json

import pytest
from mcp import Client

from sinew.db import client
from sinew.mcp_server import build_server
from sinew.tools import actions, trace

T = "sandbox"


@pytest.fixture(scope="module", autouse=True)
def _data(northwind_copy):
    yield


def q(cypher, params=None):
    return client().select_graph(T).ro_query(cypher, params or {}).result_set


def west_order(max_total=None):
    cond = "AND o.total <= $m" if max_total else ""
    return q("MATCH (o:Order)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer {region: 'west'}) WHERE NOT (o)<-[:FOR]-(:Refund) "
             f"{cond} RETURN o.id, o.total ORDER BY o.id LIMIT 1", {"m": max_total})[0]


def test_refund_within_limit_goes_through_the_pipeline():
    order, total = west_order(max_total=90)
    a = actions.issue_refund(T, "u-agent-w1", order, total, run_id="run-test")
    assert a.outcome == "answered_path"
    assert q("MATCH (r:Refund {id: $r})-[:FOR]->(:Order {id: $o}) MATCH (r)-[:APPROVED_BY]->(u:User) RETURN u.id",
             {"r": a.data["refund"], "o": order}) == [["u-agent-w1"]]
    assert q("MATCH (:AgentRun {id: 'run-test'})-[:WROTE]->(r:Refund {id: $r}) RETURN count(r)",
             {"r": a.data["refund"]}) == [[1]]


def test_refund_over_limit_names_the_approver():
    order, total = q("MATCH (o:Order)<-[:PLACED]-(:Profile)-[:OF]->(:Customer {region: 'west'}) WHERE o.total > 100 "
                     "RETURN o.id, o.total LIMIT 1")[0]
    a = actions.issue_refund(T, "u-agent-w1", order, total)
    assert a.outcome == "needs_approval" and a.data["approver"] == "u-lead-west"


def test_refund_outside_your_region_is_refused():
    order, total = west_order(max_total=90)
    assert actions.issue_refund(T, "u-agent-n1", order, total).outcome == "not_permitted"


def test_promise_proposed_confirmed_then_kept_by_the_refund():
    order, total = west_order(max_total=90)
    ticket = q("MATCH (t:Ticket) RETURN t.id LIMIT 1")[0][0]
    p = actions.record_promise(T, "u-agent-w1", ticket, order, "refund", 48).data["promise"]
    assert actions.confirm_promise(T, "u-agent-w1", p).data["status"] == "open"
    r = actions.issue_refund(T, "u-agent-w1", order, total)
    assert {"promise": p, "status": "kept"} in r.data["promises_settled"]


def test_only_leads_file_incidents():
    tickets = [r[0] for r in q("MATCH (t:Ticket)-[:TOUCHES]->(:Hub {id: 'hub-w2'}) RETURN t.id LIMIT 5")]
    assert actions.file_incident(T, "u-agent-w1", "W2 delays", tickets, "hub-w2").outcome == "not_permitted"
    a = actions.file_incident(T, "u-lead-west", "W2 delays", tickets, "hub-w2")
    assert a.outcome == "answered_path" and a.data["tickets_linked"] == 5


def test_notification_text_is_redacted():
    a = actions.notify_owner(T, "u-lead-west", "dec-courier-y", "Ask Priya Sharma (+44 7911 123456): W2 on-time is 71%")
    text = q("MATCH (n:Notification {id: $n})-[:TO]->(u:User) RETURN n.text, u.id", {"n": a.data["notification"]})[0]
    assert text[1] == "u-logistics" and "Priya" not in text[0] and "7911" not in text[0] and "71%" in text[0]


def test_findings_are_remembered():
    actions.write_finding(T, "u-lead-west", ["hub-w2", "dec-courier-y"], "W2 overload during FEST40; reroute via W4")
    r = actions.recall(T, "hub-w2")
    assert r.outcome == "answered_memory" and "reroute via W4" in r.data[0]["text"]


def test_delete_me_removes_identity_keeps_records_unlinked_and_proves_it():
    ticket = q("MATCH (t:Ticket)-[:FROM]->(:Profile)-[:OF]->(c:Customer {region: 'west'}) RETURN t.id LIMIT 1")[0][0]
    customer = trace.resolve_customer(T, ticket)
    orders = [r[0] for r in q("MATCH (:Customer {id: $c})<-[:OF]-(:Profile)-[:PLACED]->(o:Order) RETURN o.id", {"c": customer})]
    assert actions.delete_customer(T, "u-agent-w1", customer).outcome == "not_permitted"
    a = actions.delete_customer(T, "u-sup-head", customer)
    proof = a.data["proof"]
    assert proof == {"nodes_left_with_their_ids": 0, "resolves_now": None, "orders_still_linked_to_a_person": 0}
    assert q("MATCH (o:Order) WHERE o.id IN $os RETURN count(o)", {"os": orders}) == [[len(orders)]]  # kept, unlinked
    assert trace.customer_trace(T, "u-sup-head", ticket).outcome == "unknown_entity"


def run(coro):
    return asyncio.run(coro)


def test_mcp_tools_are_bound_to_a_person_and_marked():
    async def go():
        async with Client(build_server(T, "u-agent-w1")) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            result = await c.call_tool("find_approver", {"amount": 300})
            return tools, json.loads(result.content[0].text)
    tools, approver = run(go())
    assert len(tools) == 21
    assert all("user" not in json.dumps(t.input_schema) for t in tools.values())  # can't choose who it acts as
    assert tools["issue_refund"].annotations.destructive_hint is True
    assert tools["customer_trace"].annotations.read_only_hint is True
    assert "delete_customer" not in tools and "export_customer" not in tools  # human-only
    assert approver["data"]["approver"] == "u-lead-west"


def test_read_only_server_has_no_write_tools():
    async def go():
        async with Client(build_server(T, "u-sup-head", read_only=True)) as c:
            return [t.name for t in (await c.list_tools()).tools]
    names = run(go())
    assert len(names) == 14 and "issue_refund" not in names
