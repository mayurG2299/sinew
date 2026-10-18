"""AI-planned graph queries: the spec is compiled to Cypher, checked against the schema and the person's role, and
the result must equal an independent Cypher count. Every guardrail must refuse what it should."""

import pytest

from sinew.db import graph
from sinew.tools import graphquery as gq

T = "sandbox"


@pytest.fixture(scope="module", autouse=True)
def graph_(northwind_copy):
    return northwind_copy


def q(cypher, **p):
    return graph(T).ro_query(cypher, p).result_set


def run(user, spec):
    return gq.run_query(T, user, spec, "test")


PARCELS_AT_W2 = {"match": [{"label": "Hub", "id": "hub-w2"}, {"rel": "AT", "dir": "in", "label": "Scan",
                                                           "where": [{"prop": "status", "op": "in", "value": ["delayed"]}]},
                           {"rel": "FOR", "dir": "out", "label": "Shipment"}],
                 "return": [{"agg": "count_distinct", "of": "Shipment", "as": "delayed_parcels"}]}


def test_a_walk_over_three_labels_matches_an_independent_count():
    r = run("u-logistics", PARCELS_AT_W2)
    truth = q("MATCH (:Hub {id: 'hub-w2'})<-[:AT]-(sc:Scan {status: 'delayed'})-[:FOR]->(s:Shipment) RETURN count(DISTINCT s)")[0][0]
    assert r.outcome == "answered_path" and r.data["rows"] == [[truth]] and truth > 0
    assert "MATCH (v0:Hub {id: \"hub-w2\"})" in r.data["cypher"].replace("$p0", '"hub-w2"') or "hub-w2" in r.data["cypher"]
    assert "RETURN count(DISTINCT v2) AS delayed_parcels" in r.data["cypher"]


def test_a_grouped_multi_hop_count_across_five_labels():
    spec = {"match": [{"label": "Coupon", "id": "FEST40"}, {"rel": "USED", "dir": "in", "label": "Order"},
                      {"rel": "PLACED", "dir": "in", "label": "Profile"}, {"rel": "OF", "dir": "out", "label": "Customer"}],
            "group_by": [{"of": "Customer", "prop": "region", "as": "region"}],
            "return": [{"agg": "count_distinct", "of": "Order", "as": "orders"}], "order_by": {"by": "orders", "desc": True}}
    r = run("u-ceo", spec)
    truth = {row[0]: row[1] for row in q("MATCH (:Coupon {id: 'FEST40'})<-[:USED]-(o:Order)<-[:PLACED]-(:Profile)-[:OF]->(c:Customer) "
                                           "RETURN c.region, count(DISTINCT o)")}
    assert r.outcome == "answered_path" and {row[0]: row[1] for row in r.data["rows"]} == truth


def test_relative_times_and_totals():
    spec = {"match": [{"label": "Order", "where": [{"prop": "placed_at", "op": ">=", "value": "now-7d"}]}],
            "return": [{"agg": "sum", "of": "Order", "prop": "total", "as": "revenue"}, {"agg": "count", "of": "Order", "as": "orders"}]}
    r = run("u-ceo", spec)
    now = q("MATCH (m:Meta {id: 'clock'}) RETURN m.now")[0][0]
    revenue, orders = q("MATCH (o:Order) WHERE o.placed_at >= $s RETURN sum(o.total), count(o)", s=now - 7 * 86400)[0]
    assert r.data["rows"] == [[round(revenue, 2), orders]]


@pytest.mark.parametrize("bad, why", [
    ({"match": [{"label": "Hub", "id": "hub-w2"}, {"rel": "LIKES", "dir": "in", "label": "Scan"}], "return": [{"agg": "count", "of": "Scan"}]}, "no Hub"),
    ({"match": [{"label": "Hub"}, {"rel": "AT", "dir": "out", "label": "Scan"}], "return": [{"agg": "count", "of": "Scan"}]}, "no Hub"),  # wrong direction
    ({"match": [{"label": "Identifier"}], "return": [{"agg": "count", "of": "Identifier"}]}, "not something"),
    ({"match": [{"label": "Order"}], "return": [{"agg": "count", "of": "Order"}], "group_by": [{"of": "Order", "prop": "id"}]}, "identifies a customer"),
    ({"match": [{"label": "Ticket"}], "return": [{"agg": "count", "of": "Ticket"}], "group_by": [{"of": "Ticket", "prop": "summary_clean"}]}, "identifies a customer"),
    ({"match": [{"label": "Order", "where": [{"prop": "secret", "op": "=", "value": 1}]}], "return": [{"agg": "count", "of": "Order"}]}, "no property"),
    ({"match": [{"label": "Order", "where": [{"prop": "total", "op": "LIKE", "value": 1}]}], "return": [{"agg": "count", "of": "Order"}]}, "operator"),
    ({"match": [{"label": "Order"}], "return": [{"agg": "collect", "of": "Order"}]}, "agg"),
    ({"match": [{"label": "Order"}], "return": []}, "at least one"),
    ({"match": [{"label": "Hub"}] * 9, "return": [{"agg": "count", "of": "Hub"}]}, "at most"),
    ({"match": [{"label": "Order"}], "return": [{"agg": "sum", "of": "Order", "prop": "nonsense"}]}, "numeric property"),
    ("MATCH (n) DETACH DELETE n", "needs a 'match'"),
    ({"match": [{"label": "Order"}], "return": [{"agg": "count", "of": "Hub"}]}, "not part of the walk"),
])
def test_invalid_or_unsafe_specs_are_refused_with_a_reason(bad, why):
    r = run("u-ceo", bad)
    assert r.outcome == "not_in_graph" and why in r.reason, r.reason


def test_values_are_parameters_not_text():
    spec = {"match": [{"label": "Hub", "id": "x'}) DETACH DELETE h //"}], "return": [{"agg": "count", "of": "Hub"}]}
    c = gq.compile_spec(T, spec, 0)
    assert "DELETE" not in c["cypher"] and c["params"]["p0"].startswith("x'")
    assert run("u-ceo", spec).outcome == "not_in_graph"  # nothing matches; nothing deleted
    assert q("MATCH (h:Hub) RETURN count(h)")[0][0] == 8


def test_the_role_must_read_the_area_of_every_label_walked():
    assert run("u-marketing", PARCELS_AT_W2).outcome == "answered_path"  # marketing roles have operations
    assert run("u-contractor-1", PARCELS_AT_W2).outcome == "not_permitted"  # a contractor has support only
    orders = {"match": [{"label": "Order"}], "return": [{"agg": "count", "of": "Order"}]}
    assert run("u-marketing", orders).outcome == "answered_path"  # marketing may count orders (its own summary does)
    tickets = {"match": [{"label": "Ticket"}], "return": [{"agg": "count", "of": "Ticket"}]}
    assert run("u-marketing", tickets).outcome == "not_permitted"  # but not support's tickets
    costs = {"match": [{"label": "CostLine"}], "return": [{"agg": "sum", "of": "CostLine", "prop": "amount"}]}
    assert run("u-marketing", costs).outcome == "not_permitted" and run("u-cmo", costs).outcome == "answered_path"
    assert run("u-intern-nobody", orders).outcome == "not_permitted"  # unknown person: nothing


def test_the_limit_is_capped_and_reference_data_is_open_to_any_role_with_an_area():
    spec = {"match": [{"label": "Product"}], "group_by": [{"of": "Product", "prop": "category"}],
            "return": [{"agg": "count", "of": "Product"}], "limit": 5000}
    assert gq.compile_spec(T, spec, 0)["cypher"].endswith("LIMIT 50")
    assert run("u-contractor-1", spec).outcome == "answered_path"


def test_anchor_ids_match_whatever_the_case():
    spec = lambda cid: {"match": [{"label": "Coupon", "id": cid}, {"rel": "USED", "dir": "in", "label": "Order"}],
                        "return": [{"agg": "count_distinct", "of": "Order", "as": "orders"}]}
    truth = q("MATCH (:Coupon {id: 'FEST40'})<-[:USED]-(o:Order) RETURN count(DISTINCT o)")[0][0]
    assert run("u-ceo", spec("fest40")).data["rows"] == [[truth]] == run("u-ceo", spec("FEST40")).data["rows"]
