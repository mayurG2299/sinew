"""The graph tools on the real Northwind data (restored from the snapshot into the test tenant)."""

import pytest

from sinew.db import client
from sinew.tools import impact, trace

T = "sandbox"


@pytest.fixture(scope="module", autouse=True)
def _data(northwind_copy):
    yield


@pytest.fixture(scope="module")
def incident():
    a = impact.cluster_incidents(T)
    assert a.outcome == "answered_path"
    return a.data["clusters"][0]


def test_complaints_cluster_into_one_incident_rooted_at_w2(incident):
    assert incident["tickets"] == 22 and incident["issue"] == "late_delivery" and incident["root_hub"] == "hub-w2"
    shares = {s["id"]: s["share"] for s in incident["shared"]}
    assert shares["hub-w2"] == 1.0 and shares["courier-y"] == 1.0 and shares["fest40"] > 0.5


def test_clustering_leaves_no_temporary_marks_behind(incident):
    g = client().select_graph(T)
    assert g.ro_query("MATCH (t:Recent) RETURN count(t)").result_set == [[0]]
    assert g.ro_query("MATCH ()-[r:CO_TOUCH]->() RETURN count(r)").result_set == [[0]]


def test_hub_leads_to_the_courier_decision_and_the_flash_sale_link():
    a = impact.trace_decisions(T, "hub-w2")
    courier = next(d for d in a.data["decisions"] if d["decision"] == "dec-courier-y")
    assumption = courier["assumptions"][0]
    assert assumption["status"] == "broken" and assumption["value"] == pytest.approx(0.7658, abs=1e-3)
    assert assumption["linked"] == "dec-flash-sale" and "58% of parcels" in assumption["basis"]


def test_impact_of_the_courier_decision():
    d = impact.decision_impact(T, "dec-courier-y").data
    assert d["keystone_rank"] == 1
    assert {x["decision"] for x in d["dependent_decisions"]} == {"dec-2day-west", "dec-drop-backup"}
    assert d["parcels_in_transit"] == 25
    values = [c["order_value"] for c in d["customers_at_risk"]]
    assert values == sorted(values, reverse=True)
    due = [p["due_at"] for p in d["promises_at_risk"]]
    assert due and due == sorted(due)  # soonest deadline first


def test_winter_sale_is_flagged_before_launch_with_a_reroute():
    w = impact.prelaunch_check(T).data["warnings"][0]
    assert w["campaign"] == "winter25" and w["hub"] == "hub-w2" and w["starts_in_days"] == 10.0
    assert w["reroute"]["hub"] == "hub-w4" and "hub-w2" not in w["reroute"]["path"]
    g = client().select_graph(T)  # the temporary block on W2's routes is lifted again
    assert g.ro_query("MATCH ()-[r:ROUTES_TO {blocked: 1}]->() RETURN count(r)").result_set == [[0]]


def test_approver_and_choke_points():
    assert impact.find_approver(T, "u-agent-w1", 300).data["approver"] == "u-lead-west"
    assert impact.find_approver(T, "u-agent-w1", 1500).data["approver"] == "u-sup-head"
    assert impact.find_approver(T, "u-agent-w1", 50).data["self"] is True
    assert impact.choke_points(T).data[0]["hub"] == "hub-w1"


def test_agent_sees_full_trace_with_live_personal_fields(incident):
    a = trace.customer_trace(T, "u-agent-w1", incident["ticket_ids"][0])
    assert a.outcome == "answered_path"
    kinds = {i["kind"] for i in a.data["timeline"]}
    assert {"order", "payment", "scan", "ticket"} <= kinds
    assert set(a.data["personal"]) == {"name", "email", "phone"}  # fetched live, never from the graph
    assert {"field": "address", "reason": "agent may not see address"} in a.hidden
    assert a.ms < 3000  # R1: trace without the LLM in under 3 s


def test_same_customer_refused_for_other_region_and_for_marketing(incident):
    tid = incident["ticket_ids"][0]
    assert trace.customer_trace(T, "u-agent-n1", tid).outcome == "not_permitted"
    m = trace.customer_trace(T, "u-marketing", tid)
    assert m.outcome == "not_permitted" and "aggregate" in m.reason


def test_contractor_sees_only_own_queue_and_no_payments():
    g = client().select_graph(T)
    tid = g.ro_query("MATCH (t:Ticket)-[:IN]->(:Queue {id: 'q-overflow'}) RETURN t.id LIMIT 1").result_set[0][0]
    a = trace.customer_trace(T, "u-contractor-1", tid)
    assert a.outcome == "answered_path" and "q-overflow" in a.data["granted_by"]
    assert "payment" not in {i["kind"] for i in a.data["timeline"]}
    assert any(h.get("kind") == "payment" for h in a.hidden)
    assert set(a.data["personal"]) <= {"name"}


def test_every_customer_read_is_recorded(incident):
    g = client().select_graph(T)
    before = g.ro_query("MATCH (a:Access) RETURN count(a)").result_set[0][0]
    trace.customer_trace(T, "u-agent-w1", incident["ticket_ids"][0])
    trace.customer_trace(T, "u-agent-n1", incident["ticket_ids"][0])  # refused reads are recorded too
    assert g.ro_query("MATCH (a:Access) RETURN count(a)").result_set[0][0] == before + 2


def test_unknown_things_run_no_query():
    assert trace.customer_trace(T, "u-agent-w1", "o-99999").outcome == "unknown_entity"
    assert impact.trace_decisions(T, "hub-x9").outcome == "unknown_entity"
    assert trace.customer_trace(T, "u-nobody", "o-4001").outcome == "unknown_entity"


def test_related_issues_go_through_the_same_hub(incident):
    a = trace.related_issues(T, "u-agent-w1", incident["ticket_ids"][0])
    through = {d["id"]: d for d in a.data["shared"]}
    assert through["hub-w2"]["other_tickets"] >= 30
