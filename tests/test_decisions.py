import pytest

from sinew import schema
from sinew.db import client
from sinew.engine import assumptions, pipeline, promises

T = "store2"
DAY = 86_400


@pytest.fixture(autouse=True)
def fresh_graph():
    if T in client().list_graphs():
        client().select_graph(T).delete()
    schema.apply(T)
    yield
    client().select_graph(T).delete()


def ev(event_id, type_, payload, at=0, source="store"):
    return {"event_id": event_id, "type": type_, "source": source, "occurred_at": at, "payload": payload}


def q(cypher, params=None):
    return client().select_graph(T).ro_query(cypher, params or {}).result_set


def network_and_decisions():
    return [
        ev("n1", "courier.upserted", {"courier_id": "courier-y"}, source="ops"),
        ev("n2", "hub.upserted", {"hub_id": "hub-w2", "region": "west", "courier_id": "courier-y", "capacity": 10},
           source="ops"),
        ev("n3", "hub.upserted", {"hub_id": "hub-e1", "region": "east", "courier_id": "courier-y", "capacity": 10},
           source="ops"),
        # August, Ops: move the west region to Courier Y.
        ev("d1", "decision.recorded", {
            "decision_id": "dec-courier-y", "title": "Switch west region to Courier Y", "made_at": 0,
            "owner": "u-logistics", "chose_kind": "Courier", "chose_id": "courier-y", "region": "west",
            "assumptions": [{"assumption_id": "as-ontime", "statement": "Courier Y stays at least 90% on time at W2",
                             "metric": "courier_on_time_rate", "op": ">=", "threshold": 0.9, "window_days": 7,
                             "scope_hub": "hub-w2", "scope_courier": "courier-y"}]}, source="decision-log"),
        # October, Marketing: Festive Flash Sale in the west.
        ev("k1", "campaign.upserted", {"campaign_id": "fest40", "name": "Festive Flash Sale", "starts": 10 * DAY,
                                       "ends": 20 * DAY, "region": "west", "status": "running",
                                       "coupon_codes": ["FEST40"]}, source="marketing"),
        ev("d2", "decision.recorded", {
            "decision_id": "dec-flash-sale", "title": "Run the Festive Flash Sale", "made_at": 9 * DAY,
            "owner": "u-marketer", "chose_kind": "Campaign", "chose_id": "fest40", "region": "west",
            "assumptions": [{"assumption_id": "as-load", "statement": "Hub volume stays within capacity",
                             "metric": "hub_load_ratio", "op": "<=", "threshold": 1.0, "window_days": 7,
                             "scope_hub": "hub-w2"}]}, source="decision-log"),
    ]


def scans(day_from, day_to, per_day, late_every=0):
    out, n = [], 0
    for day in range(day_from, day_to):
        for i in range(per_day):
            n += 1
            sid = f"sh-{day}-{i}"
            late = 30 if late_every and n % late_every == 0 else 0
            out.append(ev(f"s{sid}", "shipment.created", {"shipment_id": sid, "order_id": f"o-{day}-{i}",
                                                          "courier_id": "courier-y", "promised_at": day * DAY}))
            out.append(ev(f"c{sid}", "scan.recorded", {"scan_id": f"sc-{sid}", "shipment_id": sid, "hub_id": "hub-w2",
                                                       "status": "delayed" if late else "in_transit",
                                                       "late_hours": late}, at=day * DAY + i, source="courier"))
    return out


def test_decisions_affect_the_same_hub():
    pipeline.process(T, network_and_decisions())
    rows = q("MATCH (d:Decision)-[:AFFECTS]->(h:Hub) RETURN d.id, h.id ORDER BY d.id")
    assert rows == [["dec-courier-y", "hub-w2"], ["dec-flash-sale", "hub-w2"]]  # not hub-e1: other region


def test_quiet_weeks_keep_the_assumption_holding():
    pipeline.process(T, network_and_decisions() + scans(1, 9, per_day=8))
    out = {r["assumption"]: r for r in assumptions.evaluate(T, now=9 * DAY)}
    assert out["as-ontime"]["holds"] is True and out["as-load"]["holds"] is True


def test_flash_sale_breaks_the_courier_assumption_and_is_linked_to_it():
    # Sale week: double the volume through W2, and 3 in 10 scans late.
    pipeline.process(T, network_and_decisions() + scans(1, 9, per_day=8) + scans(10, 17, per_day=20, late_every=3))
    out = {r["assumption"]: r for r in assumptions.evaluate(T, now=17 * DAY)}
    assert out["as-ontime"]["holds"] is False and out["as-ontime"]["value"] < 0.9
    assert out["as-load"]["holds"] is False and out["as-load"]["value"] == 2.0
    assert q("MATCH (a:Assumption {id: 'as-ontime'}) RETURN a.status") == [["broken"]]
    link = q("MATCH (d:Decision)-[r:BREAKS]->(:Assumption {id: 'as-ontime'}) RETURN d.id, r.basis")
    assert link == [["dec-flash-sale", "campaign fest40 ran in this hub's region during the window"]]
    # Evaluating again the same day adds no new evidence.
    before = q("MATCH (e:Evidence) RETURN count(e)")
    assumptions.evaluate(T, now=17 * DAY)
    assert q("MATCH (e:Evidence) RETURN count(e)") == before


def test_unclear_assumption_is_refused():
    bad = network_and_decisions()[3]
    bad = {**bad, "event_id": "bad", "payload": {**bad["payload"], "decision_id": "dec-vague",
           "assumptions": [{"assumption_id": "as-vague", "statement": "customers will be happy"}]}}
    r = pipeline.process(T, [bad])
    assert r.accepted == 0 and "not checkable" in r.quarantined[0]["reason"]


def promise_events(due):
    return [
        ev("t1", "ticket.created", {"ticket_id": "t1", "profile_id": "pf1", "channel": "chat", "queue_id": "q",
                                    "order_id": "o1", "text": "Where is my refund?"}, at=1 * DAY, source="helpdesk"),
        ev("p1", "promise.proposed", {"promise_id": "pr1", "ticket_id": "t1", "order_id": "o1", "kind": "refund",
                                      "due_at": due, "made_by": "u-ravi"}, at=1 * DAY, source="sinew-ai"),
    ]


def test_refund_before_deadline_keeps_the_promise():
    pipeline.process(T, promise_events(due=5 * DAY))
    pipeline.process(T, [ev("c1", "promise.confirmed", {"promise_id": "pr1", "confirmed_by": "u-ravi"}, at=DAY)])
    pipeline.process(T, [ev("r1", "refund.issued", {"refund_id": "rf1", "order_id": "o1", "amount": 999,
                                                    "status": "issued"}, at=4 * DAY)])
    assert q("MATCH (p:Promise {id: 'pr1'})-[:KEPT_BY]->(r:Refund) RETURN p.status, r.id") == [["kept", "rf1"]]


def test_no_action_by_deadline_breaks_the_promise():
    pipeline.process(T, promise_events(due=3 * DAY))
    pipeline.process(T, [ev("c1", "promise.confirmed", {"promise_id": "pr1", "confirmed_by": "u-ravi"}, at=DAY)])
    assert promises.due_soon(T, now=2 * DAY + 3600) == [["pr1", "refund", 3 * DAY, "u-ravi"]]  # the 24 h nudge
    assert promises.sweep(T, now=6 * DAY) == 1
    assert q("MATCH (p:Promise {id: 'pr1'}) RETURN p.status") == [["broken"]]


def test_unconfirmed_promise_is_confirmed_by_the_action_itself():
    pipeline.process(T, promise_events(due=5 * DAY))
    pipeline.process(T, [ev("r1", "refund.issued", {"refund_id": "rf1", "order_id": "o1", "amount": 999,
                                                    "status": "issued"}, at=2 * DAY)])
    assert q("MATCH (p:Promise {id: 'pr1'}) RETURN p.status, p.confirmed_by") == [["kept", "action"]]


def test_unconfirmed_promise_is_never_marked_broken():
    pipeline.process(T, promise_events(due=3 * DAY))
    assert promises.sweep(T, now=6 * DAY) == 0
    assert q("MATCH (p:Promise {id: 'pr1'}) RETURN p.status") == [["proposed"]]
