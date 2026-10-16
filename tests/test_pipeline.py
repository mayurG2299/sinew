import json
import time

import pytest
from fastapi.testclient import TestClient

from sinew import schema
from sinew.db import client
from sinew.engine import pipeline, signing
from sinew.main import app

T = "store2"
NAME, EMAIL, PHONE, ADDRESS = "Priya Sharma", "Priya.S@example.com", "+91 98200 12345", "12 Hill Road, Mumbai"


@pytest.fixture(autouse=True)
def fresh_graph():
    if T in client().list_graphs():
        client().select_graph(T).delete()
    schema.apply(T)
    yield
    client().select_graph(T).delete()


def ev(event_id, type_, payload, at=1_000, sua=None, source="store"):
    return {"event_id": event_id, "type": type_, "source": source, "occurred_at": at,
            "source_updated_at": sua, "payload": payload}


def story():
    """One customer on two channels, one order, a late scan, a ticket."""
    return [
        ev("e1", "profile.upserted", {"profile_id": "pf-web", "channel": "web", "region": "west",
                                      "name": NAME, "email": EMAIL, "phone": PHONE, "address": ADDRESS,
                                      "country": "IN"}),
        ev("e2", "profile.upserted", {"profile_id": "pf-chat", "channel": "chat", "region": "west",
                                      "phone": "098200 12345", "country": "IN"}, source="helpdesk"),
        ev("e3", "order.placed", {"order_id": "o-4412", "profile_id": "pf-web", "placed_at": 1_000,
                                  "status": "placed", "currency": "INR", "total": 2599,
                                  "coupon_code": "FEST40", "shipping_address": ADDRESS,
                                  "lines": [{"line_id": "l1", "sku": "blender-x", "batch_id": "b7",
                                             "qty": 1, "price": 2599}]}),
        ev("e4", "shipment.created", {"shipment_id": "s1", "order_id": "o-4412", "courier_id": "courier-y",
                                      "promised_at": 5_000}),
        ev("e5", "ticket.created", {"ticket_id": "t1", "profile_id": "pf-chat", "channel": "chat",
                                    "queue_id": "q-west", "order_id": "o-4412", "issue_type": "late_delivery",
                                    "text": f"Hi, I'm {NAME}. Order late! Call me on {PHONE} or {EMAIL}"},
           at=2_000, source="helpdesk"),
        # The scan arrives after the ticket: the hub link must still appear on the ticket.
        ev("e6", "scan.recorded", {"scan_id": "sc1", "shipment_id": "s1", "hub_id": "hub-w2",
                                   "status": "delayed", "late_hours": 30}, at=3_000, source="courier"),
    ]


def counts():
    g = client().select_graph(T)
    n = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    e = g.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    return n, e


def test_no_direct_identifiers_reach_the_graph():
    pipeline.process(T, story())
    g = client().select_graph(T)
    values = g.ro_query("MATCH (n) UNWIND keys(n) AS k RETURN n[k]").result_set
    values += g.ro_query("MATCH ()-[r]->() UNWIND keys(r) AS k RETURN r[k]").result_set
    blob = " ".join(str(v[0]) for v in values).lower()
    for raw in [NAME, EMAIL, PHONE, ADDRESS, "98200", "hill road"]:
        assert raw.lower() not in blob, f"{raw!r} leaked into the graph"
    summary = g.ro_query("MATCH (t:Ticket {id: 't1'}) RETURN t.summary_clean").result_set[0][0]
    assert "[PHONE]" in summary and "[EMAIL]" in summary


def test_same_phone_in_two_formats_links_both_profiles():
    pipeline.process(T, story())
    rows = client().select_graph(T).ro_query(
        "MATCH (:Profile {id: 'pf-web'})-[:HAS]->(i:Identifier)<-[:HAS]-(:Profile {id: 'pf-chat'}) "
        "RETURN i.type").result_set
    assert rows == [["phone"]]


def test_replaying_events_changes_nothing():
    pipeline.process(T, story())
    first = counts()
    pipeline.process(T, story())
    assert counts() == first


def test_older_update_never_overwrites_newer():
    pipeline.process(T, story())
    pipeline.process(T, [ev("u2", "order.updated", {"order_id": "o-4412", "status": "delivered"}, sua=9_000)])
    r = pipeline.process(T, [ev("u1", "order.updated", {"order_id": "o-4412", "status": "shipped"}, sua=8_000)])
    assert r.stale == 1
    status = client().select_graph(T).ro_query("MATCH (o:Order {id: 'o-4412'}) RETURN o.status").result_set
    assert status == [["delivered"]]


def test_ticket_touches_hub_courier_batch_whichever_arrives_first():
    r = pipeline.process(T, story())
    touched = client().select_graph(T).ro_query(
        "MATCH (:Ticket {id: 't1'})-[:TOUCHES]->(x) RETURN labels(x)[0], x.id ORDER BY x.id").result_set
    assert ["Hub", "hub-w2"] in touched and ["Courier", "courier-y"] in touched and ["Batch", "b7"] in touched
    assert {"signal": "late_scan", "shipment": "s1", "hub": "hub-w2"} in r.signals


def test_unknown_field_is_quarantined_without_its_payload():
    r = pipeline.process(T, [ev("bad", "profile.upserted", {"profile_id": "p9", "channel": "web",
                                                            "region": "west", "aadhaar": "1234 5678 9012"})])
    assert r.accepted == 0 and r.quarantined[0]["event_id"] == "bad"
    g = client().select_graph(T)
    assert g.ro_query("MATCH (p:Profile {id: 'p9'}) RETURN count(p)").result_set[0][0] == 0
    q = g.ro_query("MATCH (q:Quarantine {id: 'bad'}) RETURN q").result_set[0][0]
    assert "1234" not in json.dumps(q.properties)


def test_personal_fields_become_a_pointer_to_the_source():
    pipeline.process(T, story())
    rows = client().select_graph(T).ro_query(
        "MATCH (:Profile {id: 'pf-web'})-[:STORED_AT]->(r:PersonalRef) RETURN r.source, r.record, r.fields"
    ).result_set
    assert rows == [["store", "pf-web", ["address", "name"]]]


def test_freshness_watermark_per_source():
    pipeline.process(T, story())
    rows = dict(client().select_graph(T).ro_query(
        "MATCH (s:Source) RETURN s.id, s.last_event_at").result_set)
    assert rows["courier"] == 3_000 and rows["helpdesk"] == 2_000


def test_ingest_rejects_bad_signature_and_accepts_good_one():
    api = TestClient(app)
    body = json.dumps({"events": story()[:1]}).encode()
    ts = int(time.time())
    bad = api.post(f"/api/ingest/{T}", content=body,
                   headers={"X-Sinew-Timestamp": str(ts), "X-Sinew-Signature": "0" * 64})
    assert bad.status_code == 401
    old = api.post(f"/api/ingest/{T}", content=body,
                   headers={"X-Sinew-Timestamp": str(ts - 3600), "X-Sinew-Signature": signing.sign(body, ts - 3600)})
    assert old.status_code == 401
    good = api.post(f"/api/ingest/{T}", content=body,
                    headers={"X-Sinew-Timestamp": str(ts), "X-Sinew-Signature": signing.sign(body, ts)})
    assert good.status_code == 200 and good.json()["accepted"] == 1
