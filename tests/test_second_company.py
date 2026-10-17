"""Larkspur: a second company whose data arrives in other shapes. Same engine, same tools, no code changes."""

import copy
import json
import shutil

import pytest

from sinew.db import client
from sinew.engine import mapping, snapshot
from sinew.tools import guard, impact, trace

T = "sandbox"
CONTRACT = json.loads((mapping.SEED / "contracts" / "larkspur.json").read_text())
SOURCES = mapping.SEED / "source" / "larkspur"


@pytest.fixture(scope="module")
def larkspur(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ls")
    real_snapshots, real_records = snapshot.SNAPSHOTS, guard.SOURCE_RECORDS
    shutil.copy(real_snapshots / "larkspur.json.gz", tmp / f"{T}.json.gz")
    shutil.copy(real_records / "larkspur_personal.json", tmp / f"{T}_personal.json")
    snapshot.SNAPSHOTS, guard.SOURCE_RECORDS = tmp, tmp
    snapshot.restore(T)
    yield T
    client().select_graph(T).delete()
    snapshot.SNAPSHOTS, guard.SOURCE_RECORDS = real_snapshots, real_records


def test_contract_maps_every_record_and_skips_test_orders():
    events, held = mapping.apply(CONTRACT, SOURCES)
    store = json.loads((SOURCES / "store.json").read_text())
    real_orders = [o for o in store["orders"] if not o["test"]]
    assert held == []
    assert sum(e["type"] == "order.placed" for e in events) == len(real_orders)
    order = next(e for e in events if e["type"] == "order.placed")
    assert order["payload"]["order_id"].startswith("o-") and isinstance(order["payload"]["total"], float)


def test_courier_codes_and_minutes_are_translated():
    events, _ = mapping.apply(CONTRACT, SOURCES)
    scans = [e["payload"] for e in events if e["type"] == "scan.recorded"]
    assert {s["status"] for s in scans} <= {"in_transit", "delayed", "delivered"}
    assert all(isinstance(s["late_hours"], int) for s in scans)
    assert any(s["late_hours"] >= 15 for s in scans if s["status"] == "delayed")


def test_an_unknown_coded_value_is_held_not_guessed(tmp_path):
    for f in SOURCES.iterdir():
        shutil.copy(f, tmp_path / f.name)
    tracking = json.loads((tmp_path / "tracking.json").read_text())
    tracking[0]["checkpoints"][0]["status_code"] = 9  # a code the courier just started sending
    (tmp_path / "tracking.json").write_text(json.dumps(tracking))
    events, held = mapping.apply(copy.deepcopy(CONTRACT), tmp_path)
    assert held == [{"source": "scans", "key": f"{tracking[0]['tracking_number']}-0",
                     "reason": "value 9 has no entry in value map 'tracking_status'"}]


def test_same_tools_tell_larkspurs_own_story(larkspur):
    c = impact.cluster_incidents(T).data["clusters"][0]
    assert c["root_hub"] == "hub-e2" and c["issue"] == "late_delivery"
    d = impact.trace_decisions(T, "hub-e2").data["decisions"][0]
    a = d["assumptions"][0]
    assert d["decision"] == "dec-courier-q" and a["status"] == "broken" and a["value"] < 0.92
    assert a["linked"] is None  # no other decision overlaps: none is invented
    assert impact.prelaunch_check(T).outcome == "not_in_graph"
    assert impact.decision_impact(T, "dec-courier-q").data["keystone_rank"] is None


def test_helpdesk_and_store_profiles_merge_into_one_customer(larkspur):
    rows = client().select_graph(T).ro_query(
        "MATCH (c:Customer)<-[:OF]-(p:Profile) WITH c, collect(p.id) AS ps WHERE size(ps) > 1 RETURN ps LIMIT 1"
    ).result_set
    assert rows and any(p.startswith("pf-ls-") for p in rows[0][0]) and any(p.startswith("pf-hd-") for p in rows[0][0])


def test_permissions_follow_larkspurs_own_teams(larkspur):
    ticket = impact.cluster_incidents(T).data["clusters"][0]["ticket_ids"][0]
    assert trace.customer_trace(T, "u-care-e1", ticket).outcome == "answered_path"
    assert trace.customer_trace(T, "u-care-c1", ticket).outcome == "not_permitted"
    assert impact.find_approver(T, "u-care-e1", 200).data["approver"] == "u-care-lead"


def test_impact_page_shows_a_decision_even_without_a_link(larkspur, monkeypatch):
    from fastapi.testclient import TestClient

    from sinew import config
    from sinew.main import app
    monkeypatch.setattr(config, "TENANTS", (*config.TENANTS,))
    v = TestClient(app).get("/api/impact", params={"tenant": T}).json()
    assert v["impact"]["data"]["decision"] == "dec-courier-q"  # not dropped just because nothing is linked
