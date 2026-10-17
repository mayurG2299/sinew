"""Entity-anchored walks: each starts at the node the question names, returns only its facts, and agrees with
an independent Cypher count of the same thing."""

import json

import pytest

from sinew.db import graph
from sinew.tools import focus

T = "sandbox"


@pytest.fixture(scope="module", autouse=True)
def graph_(northwind_copy):
    return northwind_copy


def q(cypher, **p):
    return graph(T).ro_query(cypher, p).result_set


def test_order_detail_matches_the_graph_for_every_west_order():
    for oid, in q("MATCH (c:Customer {region: 'west'})<-[:OF]-(:Profile)-[:PLACED]->(o:Order) RETURN o.id")[:60]:
        d = focus.order_detail(T, "u-lead-west", "#" + oid[2:]).data
        total = q("MATCH (o:Order {id: $o}) RETURN o.total", o=oid)[0][0]
        refunded = q("MATCH (:Order {id: $o})<-[:FOR]-(r:Refund {status: 'issued'}) RETURN sum(r.amount)", o=oid)[0][0] or 0
        delivered = bool(q("MATCH (:Order {id: $o})-[:SHIPPED_AS]->()<-[:FOR]-(:Scan {status: 'delivered'}) RETURN 1", o=oid))
        assert d["total"] == total and d["refunded_total"] == round(refunded, 2) and d["delivery"]["delivered"] == delivered


def test_order_detail_is_small_and_finds_any_spelling():
    for ref in ("#4520", "4520", "order 4520", "o-4520"):
        r = focus.order_detail(T, "u-agent-w1", ref)
        assert r.outcome == "answered_path" and r.data["order"] == "#4520"
    assert len(json.dumps(r.data)) < 3000  # the order, not the customer's whole history


def test_order_detail_follows_the_customer_path():
    assert focus.order_detail(T, "u-agent-n1", "#4520").outcome == "not_permitted"
    contractor = focus.order_detail(T, "u-contractor-1", "#4520")
    assert "payment" not in contractor.data and contractor.hidden
    assert focus.order_detail(T, "u-agent-w1", "#99999").outcome == "unknown_entity"


def test_decision_detail_is_found_by_title_words_and_reports_the_evidence():
    d = focus.decision_detail(T, "u-logistics", "courier y switch").data
    assert d["decision"].startswith("Switch west region deliveries to Courier Y")
    a = d["assumptions"][0]
    assert a["needs"] == "at least 90%" and a["now"] == "77%" and not a["holds"]
    assert focus.decision_detail(T, "u-logistics", "office leave").outcome == "unknown_entity"


def test_a_hub_is_run_by_one_courier_after_a_courier_change():
    assert [c for c, in q("MATCH (:Hub {id: 'hub-w2'})-[:RUN_BY]->(c:Courier) RETURN c.id")] == ["courier-y"]
    assert focus.hub_status(T, "u-logistics", "Hub W2").data["run_by"] == "courier-y"
